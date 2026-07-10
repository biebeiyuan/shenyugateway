# Shenyu Gateway 缓存窗口与记忆岛设计

> 状态：Phase 1–3 已实现；Phase 4–5 暂缓
> 记录日期：2026-07-10；图片缓存补充：2026-07-11
> 范围：普通聊天窗口、Prompt Cache、星星/Mem 记忆岛、工具回环、冷启动和聊天分支

---

## 一、为什么要改

当前网关每次请求都会重新组合系统层、星星、Mem 和滚动聊天。即使大部分内容没有真正变化，只要前缀的文本、顺序或修剪起点发生变化，上游 Prompt Cache 就很难跨正常聊天轮持续命中。

已经确认的现状：

- 线上实际普通窗口上限由前端覆盖为 `168` 条非 system 消息。
- 当前修剪是逐请求滑动，不是分块修剪。
- Anthropic 路径支持显式 `cache_control`；当前网关最多使用 4 个断点。
- 星星正常注入会立即记录 activation，并在下一轮受到近期疲劳影响。
- Mem 正常注入会立即写 `last_triggered_at`，随后受到轮次去重和软冷却影响。
- 网关原生工具的内部回环会复用同一份 prepared context，因此工具第二轮通常比普通下一轮更容易命中缓存。
- 客户端工具结果会形成新 HTTP 请求，当前仍可能重新构建动态上下文。

真实数据参考：

- 最近 300 次线上星星注入，每次均为 3 颗。
- 相邻集合完全相同约 `20.4%`。
- 相邻集合和顺序都相同约 `16.1%`。
- 相邻集合至少重合 2/3 约 `43.5%`。
- 直接套用 2/3 粘性模拟，仍约有 `57%` 的请求会重写岛。
- 最近原始窗口中，最后 168 条正文字符总量中位数约 `5.2 万`，高位约 `17-18 万`；单条最大约 `3.4 万` 字符。
- 最近 `visit_web` 结果平均约 `4.3k` 字符，最大约 `13.8k` 字符；样本已经是纯文本正文，不是原始 HTML。

因此，问题不只是断点位置。窗口推进、召回副作用、工具续接、roll/编辑和历史压缩必须使用同一套状态模型。

---

## 二、术语

### 2.1 消息

请求 `messages` 数组中的一个元素。普通问答通常是两条消息；工具调用可能在一个真人轮里增加多条协议消息。

### 2.2 真人对话组（human turn group）

从一条新的真人 `user` 消息开始，到该用户意图对应的最终 `assistant` 回复结束。中间可以包含任意数量的 `assistant tool_use`、`tool_result` 和内部工具回环。

```text
user
assistant(tool_use)
tool(result)
assistant(tool_use)
tool(result)
assistant(final)
```

上例是 6 条消息，但只算 1 个真人对话组。

### 2.3 活跃工具组

已经开始、尚未产生最终回复的工具对话组。活跃工具组不得从中间修剪或压缩。

### 2.4 已消费工具组

模型已经读取工具结果并产生最终回复的工具对话组。只有已消费工具结果才可能在未来的 epoch 修剪中被压缩。

### 2.5 窗口 epoch

两次分块修剪之间的一段稳定期。epoch 内窗口起点、记忆岛锚点和已经冻结的上下文块保持不变；新消息只追加到尾部。

### 2.6 记忆岛

放在较老历史和近期连续聊天之间的一段背景上下文，包含当期星星和 Mem。它不是用户刚说的话，也不要求模型逐条回应。

---

## 三、设计不变量

1. 普通聊天按分块水位修剪，不再每轮掉两条消息。
2. 工具调用和对应结果作为原子组，不能拆开。
3. 最近 18 个真人对话组中的工具结果默认保留原文。
4. roll、原样重发和客户端工具续接不算新的真人轮。
5. 星星/Mem 每轮可以做纯召回提案，但只有岛真正变化时才提交 activation/triggered 副作用。
6. 岛未变化时必须复用上一版完整渲染文本，保证字节级稳定。
7. 大工具结果只在 epoch 修剪时替换为稳定摘要，不单独制造一次缓存失效。
8. 不设置独立于模型的固定输入 token 业务硬顶；只尊重模型真实上下文物理上限。
9. 当前真人消息、活跃工具组和最近 18 个真人对话组具有最高保留优先级。
10. 冷启动、窗口配置变化和历史分支必须产生明确的新 epoch，不能悄悄沿用不兼容的旧状态。

物理例外：如果最近 18 轮原文本身已经无法装进模型真实上下文，必须触发紧急压缩或停止继续工具回环。系统应记录该例外，不能静默违反保护区承诺。

---

## 四、分块窗口

### 4.1 基线与溢出块

令：

```text
L = 前端当前配置的非 system 消息基线
S = 溢出块消息数
H = L + S
```

初始建议：

```text
S = clamp(round_to_4(L * 20%), 20, 40)
```

常见值：

| 前端基线 L | 溢出块 S | 高水位 H |
|---:|---:|---:|
| 120 | 24 | 144 |
| 168 | 32 | 200 |
| 220 | 40 | 260 |

因此当前常用配置暂定为 `168 -> 200 -> 约 168`。这里的 32 是消息条数，不是 32 个完整问答轮。

### 4.2 修剪动作

当消息数达到高水位 `H`：

1. 等待当前活跃工具组完成；若下一次上游调用会超过物理上下文，则进入紧急路径。
2. 从最老的完整真人对话组开始删除。
3. 不在 tool_use/tool_result 中间落边界。
4. 将窗口降回不高于 `L` 的最近完整组集合。
5. 同一次操作内完成旧大工具结果替换、记忆岛重新锚定和新 epoch 创建。

因为原子组大小不固定，最终保留条数允许略高于或略低于 `L`。日志必须同时记录目标值和实际值。

### 4.3 前端配置变化

前端修改 `L` 时创建一次新 epoch：

- 增大 `L`：允许重新引入更早的客户端历史，因此接受一次集中缓存重建。
- 减小 `L`：立即按完整组缩到新基线。
- 冷启动补足量和岛锚点均使用新的 `L`。

配置变化是低频事件，不值得为了避免一次 miss 保留错误的旧窗口。

---

## 五、记忆岛

### 5.1 位置

一个 epoch 开始时，在保留窗口中给近期连续聊天留下约 32 条消息，并把岛锚定在它们之前。epoch 内锚点不移动；尾部从约 32 条自然增长到约 64 条，直到下次分块修剪。

```text
[稳定 system / tools]             BP-static
[较老且 epoch 内固定的历史]       BP-before-island
[星星 + Mem 岛]                   BP-after-island
[近期连续聊天尾部]                 BP-tail（可选/滚动）
[当前用户消息]
```

岛未变化时，可以命中岛后断点；岛变化时，仍可命中岛前断点。分块修剪发生时集中失效一次。

### 5.2 状态

每个逻辑会话 lineage 保存：

```text
island_version
star_fingerprints
mem_fingerprints
rendered_text
rendered_hash
anchor_group_id
epoch_id
created_at
last_decision_reason
```

指纹使用：

```text
(kind, id, sha256(rendered_fragment))
```

不得把分数、run_id、activation_count、last_activated_at 等波动字段放进内容指纹。

### 5.3 召回三阶段

1. `propose`：纯查询候选，不写 activation，不写 last_triggered。
2. `decide`：分别比较 Star lane 和 Mem lane。
3. `commit`：只有真正新进入岛的内容才提交一次 activation/trigger；保留旧岛只写决策日志。

### 5.4 粘性规则

- 集合重合率定义为 `intersection / max(old_size, new_size)`。
- 基础保留阈值为 `>= 2/3`，不是 `> 2/3`。
- 比较时按 ID 视为无序集合。
- 保留岛时复用旧渲染文本和旧顺序。
- 真正重写时按相关度排序，同分才按 ID 稳定排序。
- Star 和 Mem 分开决策，不能让稳定星星掩盖一条重要新 Mem。

以下情况绕过粘性，立即重写对应 lane：

- 用户直接提到某颗星、人物、地点或对象。
- 承诺到期、状态变化或明确的待处理信息出现。
- 当前岛条目被编辑、归档或删除。
- 新候选明显强于当前最弱候选。
- 空集合与非空集合发生切换。

### 5.5 阅读语义

稳定系统规则必须声明：

```text
memory_island 是网关提供的背景记忆，不是用户刚发送的新消息；
它可以自然影响理解和语气，但不要求被逐条提及或回应。
```

Anthropic 原生 messages 中间不能插入真正的 system role。岛应编码为固定边界 user message 内的独立文本 block，并由顶层稳定 system 解释其来源。OpenAI 原生可使用中间 developer/system message，但如果后续转换到 Anthropic，必须在 adapter 层转换成同样的标记文本块，不能被提升回顶层动态 system。

---

## 六、工具回环

### 6.1 两类工具路径

#### 网关原生工具

在同一个 HTTP 请求内完成：

```text
prepared context
 -> model
 -> gateway tool
 -> append tool result
 -> model again
```

上下文只构建一次。每次内部 round 只追加工具消息，不重新召回岛。

#### 客户端工具

模型把调用返回前端，前端执行后用新 HTTP 请求携带 tool result。第二个请求没有新的真人用户消息，应识别为 `client_tool_continuation`：

- 复用当前岛。
- 不提交新的 activation/trigger。
- 不推进真人轮计数。
- 将 tool result 追加到当前活跃工具组。

### 6.2 当前已有保护

- 同一内部请求中，相同工具名和参数会复用工具执行结果。
- 内部工具回环已有最大轮数限制。
- 当前修剪已经尝试避免拆开最新工具尾部。

仍需补充：

- 每次追加工具结果后的 prompt token 预估。
- 活跃/已消费工具组状态。
- 客户端工具续接识别。
- 旧工具结果的稳定摘要与原文档案。
- 工具组过大时的物理上下文保护。

---

## 七、最近 18 轮原文保护

### 7.1 定义

从当前分支末尾向前数 18 个真人对话组。roll、retry 和工具续接不会额外增加计数。

保护区内：

- 用户与助手正文保留原文。
- tool_use 和 tool_result 保持完整对应。
- 网页正文、文件内容和查询结果不做常规摘要替换。
- 消息高水位修剪时，优先删除保护区之前的旧组。

### 7.2 工具结果何时可以压缩

只有同时满足以下条件才是常规压缩候选：

1. 所在工具组已经产生最终回答，状态为 consumed。
2. 已经滑出最近 18 个真人对话组。
3. 结果达到“明显大”的阈值。
4. 当前正好发生 epoch 分块修剪或显式分支重建。
5. 原始结果已经持久化，可在需要时重新读取。

初始“明显大”建议仅用于候选判定，不是截断上限：

```text
单条 estimated_tokens >= 12k
或同一旧真人轮累计工具结果 >= 24k
或无 tokenizer 时 serialized_chars >= 48k
```

这些阈值必须通过线上分布继续调整。

### 7.3 后台预生成摘要

为了不让分块修剪当轮多等一次模型：

1. 工具组完成后，若结果达到候选阈值，在后台生成 compact digest。
2. 生成摘要不修改当前 prompt，也不影响当前 epoch cache。
3. 原文继续保留至少 18 个真人轮。
4. 滑出保护区并遇到 epoch 修剪时，若摘要已就绪，原子替换为稳定摘要。
5. 摘要失败或尚未完成时，保留原文；常规聊天不能被摘要任务阻塞。

摘要模型只做 query-aware compression，不需要成为有自主工具权限的完整 Agent。

### 7.4 摘要结构

```json
{
  "tool_name": "visit_web",
  "source": {
    "url": "...",
    "title": "..."
  },
  "original_hash": "...",
  "original_size": {
    "chars": 0,
    "estimated_tokens": 0
  },
  "query_context": "当时为什么读取它",
  "key_facts": [],
  "relevant_passages": [],
  "short_quotes": [],
  "limitations": [],
  "compacted_at": "...",
  "compactor_version": "..."
}
```

摘要必须保留 URL、原始内容 hash、关键事实和少量必要引文。完整原文存放在 prompt 外的工具结果档案中。

### 7.5 紧急例外

如果下一次模型调用已经接近真实上下文物理上限：

1. 先移除保护区以前的完整旧组。
2. 再替换保护区以前的已消费大工具结果。
3. 再动态收缩允许输出 token。
4. 若最近 18 轮原文自身仍装不下，才允许从保护区最老端开始紧急压缩。
5. 当前真人消息和当前活跃工具结果最后才处理。

每次突破 18 轮保护必须记录 `raw_protection_breached=true`、原因、压缩前后 token 和涉及组数。

---

## 八、Token 策略

### 8.1 不设置固定业务硬顶

不使用固定 `120k` 或 `150k` 作为所有模型统一输入上限。每个模型/上游维护真实上下文上限 `C`。

```text
P = 当前 prompt 估算 token
C = 模型上下文上限
R = 请求希望保留的输出空间
M = 安全余量
```

初始状态分区：

| 使用比例 | 行为 |
|---:|---|
| `< 70% C` | 不处理 |
| `70%-85% C` | 仅记录 warning |
| `85%-95% C` | 在下一个安全边界准备 compact |
| `>= 95% C` | 下一次上游调用前必须腾空间 |

### 8.2 输出空间动态收缩

当前输入变大时，不能继续无条件向上游声明很大的 `max_tokens`：

```text
effective_max_output = min(requested_max_output, C - P - M)
```

必须保留一个最低可用输出空间；如果连最低输出空间也无法满足，则进入紧急压缩或返回明确的上下文错误，不能把必然失败的请求发送给上游。

### 8.3 Token 估算

优先级：

1. 上游提供且延迟可接受的精确 count-tokens 能力。
2. 本地 provider/model 对应 tokenizer。
3. 本地快速估算器，并用历史响应中的真实 usage 校准。

Anthropic 总 prompt 用量校准时应考虑普通 input、cache creation 和 cache read 三部分，而不是只看一个字段。

---

## 九、编辑、重发、roll 和分支

每次请求把客户端历史标准化成消息/对话组指纹，并与上一份 raw client window 求最长公共前缀（LCP）。不得用 HTTP 请求次数或本地 gateway message_count 判断是否出现新真人轮。

| 事件 | 岛召回 | 推进真人轮 | epoch |
|---|---:|---:|---|
| 新真人 user | 是 | 是 | 延续，除非到水位 |
| 编辑最后一条 user 再发 | 是 | 否，尾部替换 | 通常延续 |
| 原样重发 | 否 | 否 | 延续 |
| roll assistant | 否 | 否 | 延续 |
| 客户端 tool result | 否 | 否 | 延续 |
| 编辑岛后的近期历史 | 视新 user 文本 | 否 | 延续或局部尾部重算 |
| 编辑岛前的旧历史 | 是 | 按新分支计算 | 新 epoch |
| 从旧消息处分支 | 是 | 按新分支计算 | 新 epoch |
| 前端 L 变化 | 是 | 否 | 新 epoch |

### 9.1 归档影响

当前 Supabase chat archive 对相同 `role + content` 做 hash 去重：

- 原样重发不会重复归档。
- 从未返回客户端历史的被 roll 回复不会进入 L0 归档。
- 编辑过的用户文本会作为新内容归档，但旧版本不会自动失效。

后续需要给编辑/分支增加 `branch_id` 和 `superseded_by`，或接收前端稳定 message id。否则旧版本可能继续被聊天档案召回。

本地 gateway_messages 当前会记录每次请求的最后一条 user 和每次生成的 assistant。它可用于审计，但不能继续作为真人轮数和 Mem dedupe 的唯一依据。

---

## 十、冷启动

冷启动用于换窗口连续，不应成为第二套窗口算法。

新线程建立时：

1. 读取前端当前 `L`。
2. 从来源线程最新 surviving client snapshot 提取完整真人对话组。
3. 补足到 `L`，不额外叠加独立的 108 上限。
4. 携带上一版岛的渲染文本、指纹和版本，但不重复提交 activation/trigger。
5. 在新线程创建新 epoch，并按新窗口重新选择岛锚点。
6. 接受换线程时的一次集中缓存重建。

若 `COLD_START_MESSAGE_LIMIT` 为空，则继承前端/运行时 `L`；只有显式配置时才单独覆盖。

---

## 十一、协议与断点

### 11.1 Anthropic 原生

已实现最多四个显式断点：

1. 稳定 system/tools 末尾。
2. 记忆岛之前的固定历史末尾。
3. 记忆岛末尾。
4. 当前 user 消息最后一个可缓存内容块。

原生 Anthropic 默认 `ANTHROPIC_CACHE_TTL=1h`。真实聊天相邻请求经常超过 5 分钟，短 TTL 会使稳定前缀在下一轮之前过期。1 小时写入按基础输入价 2 倍计费，5 分钟写入按 1.25 倍计费；命中读取仍显著便宜，因此需要继续用真实日志观察写入/读取比。

图片和文档属于 Anthropic 可缓存的 user content block。当前 user 的最后一块可以是图片，第一次请求写入该前缀，下一轮在 lookback 范围内复用。图片本身只在最近两个 user 轮次中保留；进入第三个 user 轮次后替换为稳定文本痕迹。

### 11.2 OpenAI 原生或兼容中转

- 不假设所有 OpenAI-compatible relay 都理解 Anthropic `cache_control` 扩展。
- 当前透传实现默认 `OPENAI_CACHE_TTL=5m`；确认中转接受 `ttl: 1h` 后可在管理端单独切换。
- 共享相同的 epoch、岛和工具压缩状态机。
- 对支持自动 Prompt Cache 的上游，依赖字节稳定的前缀和 provider-specific cache key。
- 对明确支持显式断点的中转，再按能力协商启用。
- 协议能力必须进入请求日志，不能只记录 `protocol=openai`。

### 11.3 图片过期与历史谱系

前端会在后续轮次移除旧图片和 `message_insert_extra_bundle_*` 动态附件。它们的消失不是编辑、roll 或新分支。raw window 只保存不含图片字节的紧凑图片指纹标记，再生成一份仅供谱系比较的规范化副本，忽略图片标记、图片已读占位和动态附件；真正发往上游的 prompt 仍保留窗口策略允许的原始图片与用户文字。日志同时记录紧凑原始 common prefix 和规范化 common prefix，便于确认本轮是否忽略了瞬时变化。

---

## 十二、建议的运行时状态

```text
WindowEpochState
  lineage_id
  epoch_id
  config_version
  base_message_limit
  overflow_messages
  model_context_limit
  window_start_fingerprint
  history_group_ids
  island_anchor_group_id
  island_version
  island_rendered_text
  island_rendered_hash
  recent_raw_protection_turns = 18
  last_client_window_fingerprint
  token_estimate
  reset_reason

ToolGroupState
  group_id
  status = active | consumed
  user_message_fingerprint
  tool_calls
  raw_result_refs
  raw_total_chars
  estimated_tokens
  compact_digest_ref
  compact_status
  final_assistant_fingerprint
```

状态应持久化到本地 SQLite，避免容器进程内状态丢失。需要跨窗口时，由 cold-start snapshot 显式携带 lineage/岛状态，而不是依赖全局 session_tag 猜测。

---

## 十三、分阶段落地

### Phase 0：设计记录

- 固化术语、状态机、参数和不变量。
- 不改运行行为。

### Phase 1：只观测，不改变 Prompt

- 构建标准化真人对话组解析器。
- 增加 LCP 事件分类：new_user、retry、roll、client_tool_continuation、branch。
- 增加 token 估算和实际 usage 校准。
- 记录假想 epoch reset、18 轮保护和工具压缩候选。
- 用真实日志验证误判率。

### Phase 2：原子分块修剪

- 引入 `L/S/H`。
- 按完整真人对话组修剪。
- 处理最新工具尾部超编和 token 物理保护。
- 冷启动改为继承 `L`。

### Phase 3：状态化记忆岛

- 召回改为 propose/decide/commit。
- 持久化岛渲染文本与指纹。
- Star/Mem 分 lane 滞回。
- 在 Anthropic/OpenAI adapter 分别落正确的岛表示与缓存策略。

### Phase 4：大工具结果档案与压缩

- 持久化 raw tool result。
- 后台预生成 compact digest。
- 实施最近 18 真人轮原文保护。
- 只在 epoch reset 时替换旧大结果。

### Phase 5：分支与归档语义

- 支持 branch_id/message_id/superseded_by。
- 修正本地真人轮计数和 Mem dedupe 数据源。
- 完成跨线程 lineage 状态传递。

每个 Phase 单独提交和验证，不把所有行为一次上线。

---

## 十四、日志与验收指标

每个请求至少记录：

```text
event_class
epoch_id
epoch_age_human_turns
base_limit / high_water / retained_messages
human_groups_before / after
island_decision = retained | rewritten | forced
island_overlap_star / island_overlap_mem
cache_breakpoints
cache_read / cache_creation
estimated_prompt_tokens / actual_prompt_tokens
context_usage_ratio
active_tool_group_messages / tokens
raw_protected_turns
tool_results_compacted
raw_protection_breached
reset_reason
```

核心验收：

- 普通连续聊天两次 epoch reset 之间，历史前缀保持稳定。
- roll/retry 不推进 epoch，不重复 activation/trigger。
- 客户端工具续接不重新召回岛。
- 任何 tool_result 都能找到对应 tool_use。
- 常规修剪不会压缩最近 18 个真人轮的原始工具结果。
- 岛保留时渲染文本字节完全一致。
- 模型 context overflow 错误为 0；若触发保护区突破，日志可完整解释。
- Supabase 归档不因普通滑窗重发重复写入。

---

## 十五、当前已定与待定

### 已定

- 当前常用 `L=168` 时，默认溢出块为 32 条消息，高水位 200。
- 分块修剪按完整真人对话组执行。
- 最近 18 个真人对话组保留原始工具结果。
- 旧大工具结果只在 epoch reset 时替换。
- 摘要可后台预生成，但不能提前改变 Prompt。
- 不设置固定 120k/150k 输入业务硬顶。
- 只有模型物理上下文可以强制触发紧急处理。
- 星星/Mem 岛采用纯召回、滞回决策、按岛版本提交副作用。
- 普通星星关键词命中不再绕过 2/3 滞回阈值；只有显式 `force_island_rewrite` 候选才立即换岛。
- Anthropic 默认 1 小时缓存，OpenAI-compatible 默认 5 分钟，两者独立开关和配置。
- 图片按最近两个 user 轮次保留，旧图片/动态附件过期不触发 branch reset。

### 待真实数据校准

- 不同模型和中转的真实 context limit。
- `12k token / 24k per turn / 48k chars` 工具压缩候选阈值。
- 记忆岛近期尾部初始 32 条是否需要按真人组动态调整。
- Anthropic 1h TTL 的实际写入/读取成本比，以及是否需要按层混合 TTL。
- compact digest 使用的具体小模型、失败重试和隐私策略。
- OpenAI-compatible 中转对显式 `cache_control` 的真实支持矩阵。
