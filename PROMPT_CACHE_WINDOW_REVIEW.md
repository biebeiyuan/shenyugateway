# PROMPT_CACHE_WINDOW_DESIGN 实现审查报告

> 审查日期：2026-07-10
> 审查范围：基于 `PROMPT_CACHE_WINDOW_DESIGN.md` 的全部未提交修改（30 个已修改文件 + 6 个新增文件）
> 审查基准提交：`2b0a0d3`

---

## 一、总体结论

本次修改是设计文档 **Phase 1（只观测）、Phase 2（原子分块修剪）、Phase 3（状态化记忆岛）** 三个阶段的合并落地。实现与设计文档的核心不变量高度吻合，逻辑自洽，374 个测试全部通过，无回归。

**评级：通过，可提交。** 下列若干细节建议在后续 Phase 中补齐。

---

## 二、设计文档要点回顾

文档要解决的核心问题：网关每轮重新组合 system/星星/Mem/滚动聊天，前缀文本或顺序变化导致上游 Prompt Cache 无法跨轮持续命中。

文档提出了 10 条设计不变量、5 个术语定义、`L/S/H` 分块水位模型、记忆岛三阶段召回（propose/decide/commit）、最近 18 轮原文保护、以及 6 个阶段（Phase 0–5）的分步落地计划。

---

## 三、实现总览

### 3.1 新增文件

| 文件 | 职责 | 对应设计章节 |
|---|---|---|
| `shenyu_gateway/context_window.py` | 真人对话组解析、LCP 事件分类、`L/S/H` 分块修剪、epoch 状态机 | §二、§四、§九 |
| `shenyu_gateway/memory_island.py` | 记忆岛渲染、propose/decide/commit、2/3 粘性、内容指纹、字节级复用 | §五 |
| `shenyu_gateway/store/_window_state.py` | epoch 状态 + 窗口事件的 SQLite 持久化 | §十二、§十四 |
| `scripts/context_window_observer.py` | 离线汇总窗口事件（epoch reset、岛决策、保留条数分布） | §十四 |
| `tests/test_memory_island.py` | 岛粘性、强制重写、内容变化检测测试 | — |
| `tests/test_context_window_observer.py` | 观测器汇总逻辑测试 | — |

### 3.2 核心修改文件

| 文件 | 改动要点 | 对应设计章节 |
|---|---|---|
| `prepare_messages.py` | 用 `select_chunked_window` 替换 `trim_client_messages`；接入 LCP 事件分类；冷启动优先级 L > COLD_START；桥消息前置到窗口选择前 | §四、§九、§十 |
| `context_builder.py` | 接入 `resolve_memory_island`；retry/roll/continuation 时复用旧岛不召回；propose 阶段不写副作用，commit 阶段只对新进入项写 | §五.3、§六.1 |
| `context_layers.py` | 岛从 prefix 层移到历史中间锚点插入；新增 `_MEMORY_ISLAND_POLICY` 稳定系统说明 | §五.1、§五.5 |
| `upstream_adapter.py` | Anthropic 路径：岛编码为 `<memory_island>` user 消息文本块；断点改为 system.end / before_island / memory_island | §五.5、§十一.1 |
| `upstream_client.py` | 新增 `enable_anthropic_cache_control` 开关；`max_breakpoints=0` 时禁用断点 | §十一 |
| `stars/_crud.py` + `stars/_recall.py` | `search_context` 拆分 propose（`mark_activation=False`、`ignore_recent_fatigue=True`）与 commit（`activate_context_items`） | §五.3 |
| `mem_notes/_search.py` | `search_notes_contextual` 拆分 propose（`mark_triggered=False`、`ignore_retrigger_limits=True`）与 commit（`mark_context_items_triggered`） | §五.3 |

---

## 四、不变量逐条对照

### ✅ 不变量 1：分块水位修剪，不再每轮掉两条

**实现**：`select_chunked_window()` 实现了完整的 `L/S/H` 模型。`overflow_messages_for_limit()` 精确实现了 `S = clamp(round_to_4(L * 20%), 20, 40)`：

- L=168 → 168×0.20=33.6 → round(33.6/4)×4 = 32 → H=200 ✅
- L=120 → 24 → H=144 ✅
- L=220 → 40 → H=260 ✅

高水位触发时按完整组修剪并创建新 epoch，非高水位时窗口起点保持不变。

### ✅ 不变量 2：工具调用和结果作为原子组

**实现**：`human_turn_groups()` 以 `role=="user"` 消息为分界，`group_safe_start()` 确保修剪边界落在组边界上。测试 `test_chunked_window_never_splits_latest_tool_group` 验证了 limit=2 时仍保留完整的 user→assistant(tool_use)→tool 三条消息。

### ⚠️ 不变量 3：最近 18 个真人对话组保留原始工具结果

**部分实现**：`raw_protected_turns` 已在 state 和 meta 中记录（`min(len(groups), 18)`），但实际的工具结果压缩/保护机制（Phase 4）尚未实现。当前只是观测和记录，不影响行为。**符合分阶段计划。**

### ✅ 不变量 4：roll/retry/客户端工具续接不算新真人轮

**实现**：`classify_history_event()` 通过 LCP（最长公共前缀）精确分类 7 种事件：

| 事件 | 判定条件 | new_human_turn |
|---|---|---|
| `retry` | 前缀完全相同，长度也相同 | False |
| `new_user` | 前缀=旧长度，追加了含 user 的消息 | True |
| `client_tool_continuation` | 前缀=旧长度，追加了 tool/tool_calls 但无 user | False |
| `continuation` | 前缀=旧长度，追加了非 user 非 tool 消息 | False |
| `roll` | 前缀=新长度，当前比旧短 | False |
| `edit_tail` | 分歧点在最后一组内 | 视末尾角色 |
| `branch` | 分歧点在非尾部组 | True |

`context_builder.py` 中 `reuse_previous_island` 对 `retry/roll/client_tool_continuation/continuation` 直接复用旧岛，不触发召回。

### ✅ 不变量 5：只有岛真正变化时才提交副作用

**实现**：`resolve_memory_island()` 的三阶段设计：

1. **propose**：`context_builder` 调用 star/mem 搜索时传 `mark_activation=False`、`mark_triggered=False`、`ignore_recent_fatigue=True`、`ignore_retrigger_limits=True`——纯查询，不写任何副作用。
2. **decide**：`_choose_lane()` 按内容指纹、重叠率、强制条件逐 lane 决策。
3. **commit**：只有 `entering` 列表（新进入岛的项）才调用 `activate_context_items()` / `mark_context_items_triggered()`。

### ✅ 不变量 6：岛未变化时复用上一版完整渲染文本

**实现**：`resolve_memory_island()` 计算 `rendered_hash = sha256(rendered_text)`，与 `previous_state["rendered_hash"]` 比较。未变化时直接复用旧文本对象，保证字节级稳定。测试 `test_memory_island_reuses_exact_rendered_text_when_proposal_only_reorders_items` 验证了即使提案顺序不同，保留时仍用旧顺序和旧文本。

### ❌ 不变量 7：大工具结果只在 epoch 修剪时替换为稳定摘要

**未实现**（Phase 4）。设计文档明确标注"token 上限和工具结果压缩暂缓"。当前状态正确地只观测不执行。

### ✅ 不变量 8：不设置固定输入 token 业务硬顶

**实现**：本次修改未引入任何固定 token 硬顶。`select_chunked_window` 只按消息条数管理窗口，token 估算和物理上下文保护留待后续。

### ⚠️ 不变量 9：当前真人消息、活跃工具组和最近 18 轮最高保留优先级

**部分实现**：原子组边界保护已实现（不变量 2），18 轮保护已记录但未强制执行（不变量 3）。活跃工具组的高水位延迟已实现：`high_water_deferred` 在 `client_tool_continuation` 事件时延迟修剪。

### ✅ 不变量 10：冷启动/配置变化/分支产生新 epoch

**实现**：`select_chunked_window()` 检测三种 epoch 重置条件：

1. `base_limit != limit` → `config_changed`
2. `event_class in {"initial", "branch"}` → `initial_window` / `history_branch`
3. `len(retained) > high_water` → `message_high_water`

冷启动优先级从 `cold_start_message_limit or max_client_messages` 改为 `max_client_messages or cold_start_message_limit`，符合 §十"若 COLD_START_MESSAGE_LIMIT 为空，则继承前端/运行时 L"。

---

## 五、记忆岛逻辑深度审查

### 5.1 粘性规则

`_overlap()` 实现 `intersection / max(old_size, new_size)`，阈值默认 `2/3`（含等于，符合 §五.4"基础保留阈值为 >= 2/3"）。

测试 `test_memory_island_retains_two_thirds_overlap_until_candidate_is_explicitly_forced` 验证：普通关键词候选即使有 `explicit_score > 0`，2/3 重叠时仍保留旧岛；只有候选显式携带 `force_island_rewrite` 才强制重写。

### 5.2 强制重写绕过条件

`_has_forced_new_item()` 实现了两种强制条件：

- **Star**：显式 `force_island_rewrite` 标记
- **Mem**：`search_mode == "entity"` 或 `memory_kind == "promise"`（实体命中或承诺到期）

加上 `_choose_lane()` 中的 `content_changed`（内容指纹变化）和 `empty_transition`（空↔非空切换），覆盖了设计 §五.4 的主要绕过场景。

**缺失**：设计提到的"当前岛条目被编辑、归档或删除"和"新候选明显强于当前最弱候选"两个条件未显式实现。前者依赖内容指纹变化间接覆盖；后者未实现。

### 5.3 指纹设计

`_fingerprints()` 使用 `sha256(rendered_fragment)`，不包含分数、run_id、activation_count 等波动字段，符合 §五.2"不得把分数、run_id、activation_count、last_activated_at 等波动字段放进内容指纹"。

### 5.4 协议适配

- **Anthropic**：岛编码为 `{"role": "user", "content": [{"type": "text", "text": "<memory_island source=\"gateway_background\">..."}]}`，由顶层稳定 system 的 `_MEMORY_ISLAND_POLICY` 解释来源。符合 §五.5"岛应编码为固定边界 user message 内的独立文本 block"。
- **OpenAI-compatible**：岛作为普通 system 消息插入历史中间，`INTERNAL_LAYER_KEY` 在 sanitize 时剥离。

---

## 六、缓存断点策略审查

### 6.1 Anthropic 路径

断点分配（最多 4 个）：

| 顺序 | 断点位置 | 设计 §十一.1 对应 |
|---|---|---|
| 1 | `system.end`（最后一个 system block） | ① 稳定 system/tools 末尾 |
| 2 | `before_island`（岛前一条消息） | ② 记忆岛之前的固定历史末尾 |
| 3 | `memory_island`（岛本身） | ③ 记忆岛末尾 |
| 4 | 当前 user 最后一个可缓存内容块 | ④ 近期尾部滚动延伸点 |

Anthropic 与 OpenAI-compatible 路径都把第 4 个断点放在当前 user 的最后一个可缓存内容块；当最后一块是图片时，图片本身进入下一轮可复用的前缀。Anthropic 默认使用 1 小时 TTL，OpenAI-compatible 保留独立可配置 TTL。

### 6.2 OpenAI-compatible 路径

岛通过内容文本匹配定位，在岛前和岛上各加一个断点。system 层断点选择最后一个匹配的非空 system 消息（`_SYSTEM_CACHE_LAYER_PREFERENCE` 按优先级匹配）。

**改进**：`enable_anthropic_cache_control` 新增开关，`max_breakpoints=0` 时彻底禁用断点，`cache_meta.enabled` 改为反映实际添加的断点数而非协议类型。

---

## 七、问题与风险

### 7.1 死代码

| 函数 | 状态 | 建议 |
|---|---|---|
| `_trim_cold_start_snapshot()` (prepare_messages.py:70) | 定义存在，全项目无调用 | 删除 |
| `trim_client_messages()` (context_layers.py:241) | 仅被测试引用，主流程已替换为 `select_chunked_window` | 保留测试或一并迁移 |

### 7.2 桥消息与窗口选择的交互

桥消息（冷启动）现在在 `select_chunked_window` 之前通过 `insert_bridge_messages` 注入，成为窗口输入的一部分。这意味着：

- 桥消息受 epoch 窗口逻辑管理，新消息增长时桥消息自然老化退出。✅
- 如果 `window_start_index` 超过桥消息范围，`trim_meta["cold_start_bridge_messages"]` 归零，快照被标记完成并清除。✅
- 但如果窗口已满且桥消息仍在保护区内，桥消息会占位压缩正常历史。这是合理的行为，但应在 Phase 4 token 保护中复查。

### 7.3 `activate_context_items` 静默异常

`stars/_crud.py` 中 `activate_context_items` 对 candidate 表更新有 `try/except: pass`，可能静默吞掉 Supabase 写入失败。建议至少记录 warning 日志。

### 7.4 岛锚点在 epoch 内不移动

设计 §五.1 要求"epoch 内锚点不移动"。实现中非 epoch-reset 时从 `previous_state` 恢复锚点，并 clamp 到当前 retained 长度内。✅ 符合设计。

### 7.5 Room 模式路径

Room 模式也接入了 `select_chunked_window` 和状态持久化，但未接入记忆岛逻辑。这是合理的——room 模式有自己的上下文模型。

### 7.6 观测完备性

`log_context_window_event` 记录了 trim_meta、event_meta、memory_island_decision、memory_island_version。但设计 §十四要求的部分字段未记录：

- `epoch_age_human_turns` ❌
- `cache_read / cache_creation` ❌（需上游 usage 回填）
- `estimated_prompt_tokens / actual_prompt_tokens` ❌
- `context_usage_ratio` ❌
- `active_tool_group_messages / tokens` ❌
- `tool_results_compacted` ❌（Phase 4）
- `raw_protection_breached` ❌（Phase 4）

这些缺失字段大多依赖 Phase 4 的 token 估算和工具压缩能力，当前阶段不记录是可接受的。

---

## 八、测试验证

```
374 passed, 2 warnings in 9.32s
```

新增测试覆盖：

| 测试文件 | 关键测试 | 验证点 |
|---|---|---|
| `test_memory_island.py` | `reuses_exact_rendered_text_when_proposal_only_reorders_items` | 岛保留时字节级复用 |
| | `retains_two_thirds_overlap_but_direct_candidate_forces_rewrite` | 2/3 粘性 + 强制重写 |
| | `rewrites_when_existing_item_content_changes` | 内容指纹变化触发重写 |
| `test_context_window_observer.py` | `summarizes_events_without_message_content` | 观测器汇总正确 |
| `test_gateway_trim.py` | `test_chunked_window_keeps_start_until_high_water_then_resets` | L/S/H 水位 + epoch 延续/重置 |
| | `test_chunked_window_never_splits_latest_tool_group` | 原子组不被拆分 |
| | `test_mem_island_sits_after_system_layers_before_recent_chat_history` | 岛位置正确 |
| `test_gateway_store.py` | `test_context_window_state_round_trip` | epoch 状态持久化 |
| `test_config_update.py` | `test_config_update_saves_anthropic_cache_control` | 新配置开关 |
| `test_gateway_streaming.py` | （扩展） | 缓存断点 + 岛编码 |

---

## 九、优化逻辑评价

### 9.1 核心逻辑正确性

**LCP 事件分类**是整个改造的基础。通过比对上一份 raw client window 的指纹前缀来判断事件类型，而非依赖 HTTP 请求次数或本地 message_count，这从根本上解决了设计 §九提出的问题。`message_fingerprint()` 使用 `sha256(stable_json(role, content, name, tool_call_id, tool_calls))`，稳定且抗序列化差异。

**记忆岛三阶段**将"召回"和"副作用"解耦，是本次改造最有价值的架构改进。之前每次召回都立即写 activation/fatigue，导致相邻轮次间岛频繁变化。现在 propose 阶段纯查询、commit 阶段只对新进入项写副作用，配合 2/3 粘性和字节级文本复用，能显著提升缓存命中率。

**分块修剪**用 `L → H → L` 的水位模型替代了逐轮滑动，使窗口前缀在 epoch 内保持稳定。epoch 内锚点不移动、岛文本不变，为上游 Prompt Cache 提供了稳定的可命中前缀。

### 9.2 架构合理性

- **状态持久化到 SQLite**：`context_window_states` 表以 session_id 为主键，避免容器重启丢失 epoch 状态。符合 §十二"状态应持久化到本地 SQLite"。
- **冷启动继承岛状态**：`prepare_messages.py` 中从 cold-start source session 的 window_state 提取 `island_state`，实现跨线程岛状态传递。符合 §十.4"携带上一版岛的渲染文本、指纹和版本"。
- **协议无关的状态机**：epoch、岛、窗口逻辑在 `context_window.py` / `memory_island.py` 中与协议无关，Anthropic/OpenAI adapter 分别只负责表示和断点。符合 §十一.2"共享相同的 epoch、岛和工具压缩状态机"。

### 9.3 需要关注的设计张力

1. **岛位置与缓存命中**：岛插入在历史中间（锚点偏移处），岛前的历史是缓存可命中前缀的一部分。岛未变化时岛后断点可命中；岛变化时岛前断点仍可命中——这正是设计 §五.1 的意图。实现正确。

2. **桥消息前置的影响**：将桥消息从 `assemble_layered_messages` 内部插入改为在 `select_chunked_window` 前注入，使桥消息受窗口逻辑管理。桥消息不再被特殊保护，而是与正常历史平等竞争窗口空间。冷启动后第一轮不是问题（窗口未满），但长期影响需在 Phase 4 复查。

3. **观测先行**：`context_window_observer.py` 和 `log_context_window_event` 的存在表明团队选择了"先观测再改"的策略（Phase 1），与设计文档的分阶段计划一致。当前已有足够观测数据来校准后续 Phase 参数。

---

## 十、结论与建议

### 已完成

| 设计 Phase | 状态 | 说明 |
|---|---|---|
| Phase 0：设计记录 | ✅ | 文档已固化 |
| Phase 1：只观测 | ✅ | 事件分类、epoch 状态、岛决策已记录到 SQLite |
| Phase 2：原子分块修剪 | ✅ | L/S/H 水位、完整组修剪、epoch 状态机 |
| Phase 3：状态化记忆岛 | ✅ | propose/decide/commit、2/3 粘性、字节级复用、持久化 |
| Phase 4：工具结果压缩 | ❌ | 设计标注暂缓 |
| Phase 5：分支与归档 | ❌ | 未实现 |

### 提交前建议

1. **删除死代码**：`_trim_cold_start_snapshot()` 已无调用方。
2. **补充异常日志**：`activate_context_items` 中的 `except: pass` 至少记录 warning。
3. **文档同步**：在 `PROMPT_CACHE_WINDOW_DESIGN.md` 顶部状态行更新为"Phase 1–3 已实现；Phase 4–5 暂缓"。

### 后续 Phase 建议

1. **Phase 4 优先级最高**：18 轮保护当前只记录不执行，大工具结果无压缩，长对话可能逼近物理上下文上限。
2. **补齐观测字段**：`epoch_age_human_turns`、`estimated_prompt_tokens` 等字段对校准 Phase 4 参数至关重要。
3. **Anthropic tail 断点**：在 Phase 4 token 估算就绪后评估是否值得增加第 4 个断点。

---

*审查人：Cline AI Coding Agent*
