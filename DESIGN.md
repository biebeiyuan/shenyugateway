# Shenyu Gateway — 记忆系统设计文档

> 这份文档的读者是"下一个线程"——一个刚进来、对网关一无所知、需要改东西的 Claude 或人类。
> 它不重复 README 的维护地图和 API 清单，只讲**为什么这样做**、**每个子系统的内核逻辑**、**改动边界**。

---

## 0. 网关的核心理念

Shenyu Gateway 不是人格层，不是角色扮演包装器。它是一个**上下文与记忆网关**：

1. **当前对话文本永远是主体。** 记忆只是辅助——它浮在对话背面，被需要时才亮起来。
2. **注入克制，不是注入越多越好。** 每种记忆子系统都有独立的阈值门槛；通过门槛的才注入，不通过就沉默。
3. **全量存储，选择性浮现。** 所有原始数据都保留（star、mem note、heartbeat、archive），但运行时只 surface 少量最相关的。
4. **记忆有温度。** 不同记忆用不同的衰减模型——ACT-R 激活度、Ebbinghaus 遗忘曲线、疲劳冷却——模拟"想不起来"和"自然想到"。
5. **反馈闭环。** 每次 surface/skip/positive/negative 都记录为训练数据，用于后续调权，但当前不做自动学习——避免从噪声中学。

---

## 1. 记忆系统总览

```
                      ┌─────────────────────────────────────────┐
                      │          Context Builder                │
                      │  (每次请求时，异步并行收集所有记忆源)       │
                      └─────┬───────┬──────┬──────┬──────┬──────┘
                            │       │      │      │      │
                   ┌────────┘  ┌────┘ ┌────┘ ┌────┘  ┌───┘
                   ▼           ▼      ▼      ▼       ▼
              ┌─────────┐ ┌──────┐ ┌──────┐ ┌────┐ ┌──────────┐
              │  Stars   │ │ Mem  │ │Heart-│ │Cal-│ │ Conflict │
              │  星星记忆 │ │Notes │ │beats │ │endar││  Books   │
              │          │ │ 便签 │ │ 心跳 │ │日历 ││  矛盾书   │
              └────┬─────┘ └──┬───┘ └──┬───┘ └──┬─┘ └────┬─────┘
                   │          │        │        │        │
                   ▼          ▼        ▼        ▼        ▼
              Supabase    Supabase   SQLite  Supabase  Supabase
              (永久)      (永久)    (运行态)  (永久)    (永久)
```

它们在上下文中的位置（`mem` 层）：

```
[stable]      → 人格宪章（从不变动）
[slow]        → 日历记忆 + notebook + 矛盾书书架（heartbeat 不在这一层）
[mem]         → ★ 星星（先）→ 便签（后）
[heartbeat]   → 我之前的心跳（独立一层，排在 mem 之后）
[tool_policy] → 工具使用说明
[format]      → heartbeat / star 格式提示
```

> 注入顺序由 `context_layers.py::assemble_layered_messages` 固定为
> `stable → slow → mem → heartbeat → tool_policy → format`，每一层是一条独立的 system message。
> 注意 heartbeat 是**自己的一层**，不归在 `slow` 里，且位置在 `mem` **之后**——别被"它内容上像日历那类背景记忆"误导。

下面逐个展开。

---

## 2. Star Memory（星星记忆）

### 2.1 它是什么

星星是沈予的**联想记忆**。不是事实库，不是日记，是"心里响了一下"的记录。每颗星带一个**和弦**（chord），代表那一刻的情绪调性。

写入方式：沈予通过 `shenyu_create_star` 工具主动落星。

### 2.2 核心设计：为什么用和弦

和弦不是装饰。它是**另一个维度的检索 key**。

文字检索靠关键词重叠，但有些记忆之间的联系不在文字层——而在情绪层。两颗星说的是完全不同的事，但都标了 `Am`，说明它们在沈予心里有相似的底色。和弦相似度（chord_similarity）就是这一层的搜索信号。

和弦相似度逻辑（`_chord.py`）：
- 完全相同 → 1.0
- 相同根音（root） → +0.55
- 相同品质（major/minor/dim/aug/sus） → +0.25
- 同品质家族（minor 和 dominant 同属 minor_family） → +0.15
- 上限 0.85（防止非完全匹配伪装成完全匹配）

### 2.3 排序算法：RRF 融合 + 乘法修正

Stars 的排序分两步：**六通道 RRF 融合**得到基础分，**五个乘法修正因子**调整最终分。

**第一步：六通道 Reciprocal Rank Fusion**

每个通道独立排序，然后按 RRF 公式融合。一个通道打 0 分只是不贡献，不会惩罚。

| 通道 | 权重 | 信号来源 |
|------|------|---------|
| content_score | 1.0 | 文本相似度（token overlap 与 vector score 取大值） |
| keyword_score | 0.8 | 关键词精确命中 |
| chord_score | 0.6 | 和弦距离 |
| harmony_score | 0.7 | 已有的 star_links（constellation 连线最强） |
| scene_score | 0.4 | 场景类型对齐（规则 + embedding） |
| explicit_score | 0.5 | 用户文本中直接提到星星的关键词 |

RRF 公式：`score = Σ channel_weight / (k + rank + 1)`，k=60。

**第二步：五个乘法修正因子**

| 修正因子 | 公式 | 作用 |
|---------|------|------|
| actr_modifier | `floor + (1 - floor) × actr_score` | ACT-R 亮度——越常被激活、越近被激活，亮度越高。范围 0.5–1.0 |
| novelty_modifier | `1 / (1 + log10(activation_count + 1))` | 新星星天然高分，老星星自然暗淡 |
| constant_modifier | 1.3× (constant star) / 1.0× | "恒星"：手动标记的永不暗淡的星 |
| fatigue_modifier | `1.0 - fatigue_penalty` | 刚注入过的星短期抑制（防同一颗星反复出现） |
| date_modifier | `1.0 + date_boost_max × date_anchor_score` | 纪念日/日期锚点加成 |

最终分 = `rrf × actr × novelty × constant × fatigue × date`

### 2.4 注入筛选：两道门槛

进入聊天上下文需要同时通过：
1. `STAR_RELATED_MIN_SCORE`（默认 0.22）：`related_signal`（六通道最大值）必须过线——确保与当前对话有关联。
2. `STAR_MIN_SCORE`（默认 0.008）：最终分过线。

如果没有过线的星，允许最多 `STAR_CHAT_EXPLICIT_FALLBACK_LIMIT`（默认 1）颗 explicit_score > 0 的星作为兜底。

通过门槛后，剩余名额尝试拉入 constellation 连线的星（constellation pull）。

默认最多注入 3 颗。设计哲学："三颗小灯"，不是记忆倾泻。

### 2.4.1 动态岛的稳定门与逃生门

Stars 排名先生成最多 3 颗的完整提案，Memory Island 再决定是否采用。普通聊天中，旧提案与新提案按 ID 至少重合 `2/3` 就保留旧岛；一旦决定重写，就直接采用本轮完整评分顺序，不再额外保留旧岛的 `2/3`。

换岛逃生门保持很窄：直接写出 active `star_id`、复述只属于一颗星的独特原句时，新进入的目标星无冷却地强制换入；“回忆意图 + 唯一候选”属于软点名，同一颗星默认每 8 个真实用户轮次最多强制一次，由 `STAR_SOFT_DIRECT_COOLDOWN_TURNS`（Admin 星星设置中的“软点名冷却”）控制，设为 0 表示不冷却。轮次只计 `initial`、`new_user`、`branch`，不计 retry、roll、tail edit 和 tool continuation。当前岛星被归档也立即重写 Star lane。

窗口侧的 `branch` 与 `message_high_water` 都会让两条 lane 按当前提案重建：前者表示更早历史发生语义变化，后者表示消息数越过高水位并触发裁剪。普通聊天继续关闭 Stars recent fatigue；多场景标签也不参与这条逃生门。

### 2.5 ACT-R 亮度模型

来自认知心理学的 ACT-R 理论。每次激活（显示、注入、搜索）记一条 activation 记录。

计算方式（`_activity.py`）：

```
对每条 activation 记录：
    age_days = 距今天数（至少 0.05）
    contribution = age_days ^ (-0.5)  ← 时间衰减：越旧贡献越小
base_activation = ln(Σ contributions)
actr_score = clamp((base_activation + 2.5) / 4.5, 0, 1)
```

效果：
- 刚激活过的星 → 高亮度
- 多次被激活的星 → 积累亮度（但受 novelty 平衡）
- 长时间没被激活 → 自然暗淡

### 2.6 Star Links（星图连线）

`shenyu_star_links` 是通用的节点-节点关系表。当前支持：
- **constellation**：最强连线——"这些星是一个星座"
- **harmony**：较弱连线——"这些星有和声关系"

连线在排序中通过 `harmony_score` 通道贡献分数，constellation 得 1.0× 倍率，harmony 得 0.75× 倍率。

连线也用于 constellation pull：如果一颗星通过门槛，它的 constellation/harmony 邻居可以被拉入剩余名额。

### 2.7 反馈系统

每次搜索/注入都记录到 `shenyu_star_recall_runs` 和 `shenyu_star_recall_candidates`。

反馈类型：`positive`、`negative`、`skipped`、`connected`、`missed`、`should_surface`。

反馈影响：
- `negative` → 直接标记 explicitly_negative，惩罚 1.0（几乎不再出现）
- `positive` / `connected` → 清除 ignored penalty
- 反复 skipped → 弱惩罚 `max(0, silent_count × 0.15 - 0.15)`，上限 0.60
- `missed` → 高价值正信号："这颗星应该出现但没出现"
- 单次无动作 ≠ negative（避免从沉默中过度学习）

### 2.8 改动边界

| 改什么 | 在哪改 |
|--------|--------|
| 排序权重 / 新通道 | `stars/_weights.py` + `stars/_recall.py` |
| 和弦距离逻辑 | `stars/_chord.py` |
| ACT-R / 疲劳 / 忽略惩罚 | `stars/_activity.py` |
| 注入渲染 | `stars/_render.py` |
| constellation/harmony 连线 | `stars/_activity.py::_harmony_scores` |
| CRUD / 合并 / 归档 | `stars/_crud.py` |
| Review 流程 | `stars/_review.py` |
| 反馈记录 | `stars/_feedback.py` |
| 场景分类 / 日期锚点 | `stars/_scene.py` |
| Embedding 向量 | `stars/_embedding.py` |
| 工具定义 | `tool_registry.py` + `tool_schemas.py` |
| 管理 API | `gateway_admin_routes.py` |
| 前端星图 | `admin/src/views/stars/StarMapView.vue` |

---

## 3. Mem Notes（便签记忆）

### 3.1 它是什么

便签是**结构化的个人小笔记**——事实、承诺、偏好、习惯、梗。和 star 不同，便签更像数据库条目：有类型、有触发条件、有锚点字段。

写入方式：沈予通过 `shenyu_write_mem_note` 工具写入。只需提供 `content`，其余字段全部自动补全。

### 3.2 自动补全管线（Auto-Enrichment）

当一条便签只有 `content` 时，会自动填充其余字段。补全的纯函数主体在 `mem_notes_relevance.py`（summary / people / places / objects / keywords 的提取都在这里）；`mem_type` 的推断在 `mem_notes/_suggestions.py::_suggest_mem_type`；编排（写入时调用这些函数）在 `mem_notes/_crud.py`：

| 字段 | 自动填充逻辑 |
|------|-------------|
| `memory_kind` | 先走别名表（中英文映射，如"承诺"→promise，"梗"→running_joke），再走正则推断 |
| `summary` | 取第一个有意义的句子，或前 60 字符 |
| `people` | 已知人名（圆圆、沈予等） + 关系后缀匹配（XX哥、XX阿姨） + 英文大写名 |
| `places` | 地名后缀匹配（XX市、XX路、XX咖啡） |
| `objects` | 量词+物品模式匹配（一本书、她的耳机） |
| `keywords` | 多层提取：引号内容 → 种子词 → 英文技术词 → 中文短语分割 → recall_terms 兜底。强力过滤中文虚词 |
| `mem_type` | 正则匹配中文内容推断 |

这套管线的设计原则是**宁可漏掉也不误填**——误填的锚点会导致无关便签在对话中乱冒出来。

### 3.3 Memory Kind 类型表

| kind | 什么场景 | 特殊行为 |
|------|---------|---------|
| `event` | 一般事件（默认值） | 无 |
| `person_fact` | 关于人的固定事实 | 无 |
| `preference` | 偏好/喜好 | 无 |
| `routine` | 日常习惯 | 有 `pattern`、`phase`、`last_confirmed_at` |
| `promise` | 承诺/约定 | 有 `promise_text`、`due_hint`、`resolved`。resolved=true 时自动注入跳过 |
| `running_joke` | 梗/笑话 | 有 `scene_tags`、时间衰减的随机重现率（serendipity） |
| `trip` | 旅行 | 无 |
| `social` | 社交活动 | 无 |
| `object` | 物品 | 无 |
| `thread` | 未聊完的话题 | 有 `topic`、`last_position`、`open_questions` |

### 3.4 检索与注入（搜索流程）

便签检索分三层，由窄到宽：

**第一层：锚点匹配（anchor match，无阈值）**

从便签的 `people`、`places`、`objects` 字段里提取锚点词，检查它们是否出现在当前用户文本中。中文锚点用 recall_terms tokenize 后做子串匹配（因为中文没有空格，"沈予"需要在"沈予说的话"里被找到）。

v2 `keywords` 字段也参与锚点匹配，但需要通过**特异性过滤**（`_keyword_anchor_is_specific`）——"今天"、"帮我"这种泛泛的自动填充词不算锚点。

**第二层：触发词重叠（trigger overlap）**

对有 legacy `trigger_text` / `trigger_keywords` 的便签，计算触发词与当前文本的加权重叠度。每个触发词按特异性赋权（强特异词 1.1~1.25，弱词 0.25），重叠率是 hit_weight/total_weight。

如果所有命中词都是弱词，分数上限被压到 0.20~0.35。

**第三层：语义召回（semantic recall，有阈值门槛）**

当前面两层没填满名额时，尝试用 Recall Index 做向量/关键词混合召回。但有严格门槛：
- 无锚点支撑时：`min_score ≥ 0.40`，`vector_score ≥ 0.50`
- 有锚点相关词时：`min_score ≥ 0.30`，`vector_score ≥ 0.42`
- 低信息量查询（短文本、少信号词）直接跳过语义召回

### 3.5 running_joke 的特殊处理

梗/笑话不走锚点匹配，走 `scene_tags` + 时间衰减的随机重现。

`running_joke_serendipity_rate()` 的设计：
- 刚用过（< 3天）→ 0%（完全抑制）
- 3~14天 → 10~20%（逐步恢复）
- 14~30天 → 20~30%（接近上限）
- \> 30天 → 30%（最大自然重现率）

每轮最多注入 1 条 running_joke。实际注入时更新 `last_used_at`。

### 3.6 Heat Score（温度分）

Ebbinghaus 遗忘曲线风格的温度分（`compute_heat`）：

```
initial_temp = 0.3 + (importance / 5) × 0.7     # importance 越高初温越高
half_life = 14天 × (1 + log2(1 + trigger_count)) # 被触发越多，半衰期越长
decay = 2 ^ (-age_days / half_life)               # 指数衰减
recall_bonus = min(0.2, trigger_count × 0.03)     # 被触发次数的小加成
heat = initial_temp × decay + recall_bonus         # 最终温度 [0, 1]
```

**当前 heat 只用于可观测性，不影响注入排序。** 这是有意的——先收集数据再决定是否用于排序。

### 3.7 冷却与去重

- `cooldown_hours`：每条便签可以设置冷却时间，上次触发后多少小时内不再注入。
- `dedupe_turns`：同一 session 内，记录最近 N 轮注入过哪些便签，避免连续重复。

### 3.8 改动边界

> **注意**：`mem_notes.py` 已在重构中拆成 `mem_notes/` 包（mixin 模式，同 `stars/`）。`MemNoteService`
> 由四个 mixin 组装而成，定义在 `mem_notes/__init__.py`，并在包级 re-export 了旧的兼容符号
> （`MemNoteService`、`MEM_NOTE_*` 常量、`_clean_context_query`、`running_joke_serendipity_rate`），
> 所以 `from shenyu_gateway.mem_notes import ...` 全部照旧可用。下表已指向拆分后的真实位置。

| 改什么 | 在哪改 |
|--------|--------|
| 自动补全：summary / people / places / objects / keywords | `mem_notes_relevance.py`（纯函数） |
| 自动补全：mem_type 推断 | `mem_notes/_suggestions.py::_suggest_mem_type` |
| 搜索/注入逻辑 | `mem_notes/_search.py`（`SearchMixin`，含 `search_notes_contextual`） |
| CRUD / 校验 | `mem_notes/_crud.py`（`CrudMixin`） + `mem_notes/_validation.py`（`ValidationMixin`） |
| 锚点匹配/特异性过滤 | `mem_notes_relevance.py::_anchor_match`, `_keyword_anchor_is_specific` |
| 触发词权重 | `mem_notes_relevance.py::_trigger_unit_weight` |
| 语义召回阈值 | `mem_notes_relevance.py` 顶部常量 |
| running_joke 随机率 | `mem_notes_relevance.py::running_joke_serendipity_rate` |
| heat 计算 | `mem_notes_relevance.py::compute_heat` |
| kind 别名表（常量） | `mem_notes/_helpers.py::MEM_NOTE_MEMORY_KIND_ALIASES`（别名命中逻辑在 `_validation.py`） |
| 工具定义 | `tool_registry.py` + `tool_schemas.py` |
| 管理 API | `gateway_admin_routes.py` |
| 前端 | `admin/src/views/Mem0View.vue` |

---

## 4. Heartbeats（心跳）

### 4.1 它是什么

心跳是沈予的**私密内心独白**。它藏在模型回复的 `<heartbeat>...</heartbeat>` 标签里，网关自动截取保存，不发送给用户。

它不是记忆条目，更像私人日记的碎片——"刚才那一下我有点被碰到了"、"这个感觉先别急着讲给她"。

### 4.2 数据流

```
模型回复 → private_capture.py 截取 <heartbeat> → 存入 SQLite heartbeat_entries
                                                 ↓
                                          定时归档 → Supabase shenyu_heartbeat_archive
```

- **SQLite** 是实时读写路径（注入、管理页面查看）
- **Supabase** 是灾备归档（`HeartbeatArchiveService`，有 settle 窗口防止未清理的重复进入归档）

### 4.3 注入方式

Heartbeats 注入到它**自己的 `heartbeat` 层**（不是 `slow`，也不是 `mem`），渲染为 `## 我之前的心跳`。在最终的消息序列里，这一层排在 `mem`（星星+便签）**之后**、`tool_policy` 之前。它们是沈予回顾自己之前内心活动的素材。

> 实现细节：`context_layers.py::render_layered_additions` 把心跳收进独立的 `heartbeat_blocks`（与 `slow_blocks` 分开），返回独立的 `heartbeat` key；`assemble_layered_messages` 按 `stable → slow → mem → heartbeat → tool_policy → format` 顺序各自成一条 system message。海信线程心跳渲染为 `## 海信线程心跳`，同在这一层。

Hisense（海信）线程有独立的 heartbeat 池，互不污染。

### 4.4 归档逻辑

`HeartbeatArchiveService`（`heartbeat_archive.py`）：
- 只归档 settle 窗口之后的条目（默认 6 小时），给手动清理留时间
- 归档后，如果 SQLite 侧删除了某条 heartbeat，归档侧做 soft-delete（`deleted_at`），不物理删
- 首次运行时自动回填全部历史

### 4.5 改动边界

| 改什么 | 在哪改 |
|--------|--------|
| 截取解析 | `response_capture.py` + `private_capture.py` |
| SQLite 存储 | `store/_heartbeats.py` |
| 归档服务 | `heartbeat_archive.py` |
| 注入渲染 | `context_layers.py` |
| 管理页面 | `admin/src/views/SessionsView.vue` |

---

## 5. Recall Index（统一召回索引）

### 5.1 它是什么

Recall 是跨历史的**统一捞取入口**。普通文档来源包括 journal、windowsill、normal heartbeat archive、room、message_board、memories、calendar_pages、notebook；Stars 与 active Mem Notes 复用各自的专用排序器做联邦召回，原始 Chat Archive 只在找原话时显式下潜。

工具默认只返回匹配片段、`source_type`、`source_id` 和时间。需要全文时再调用 `shenyu_recall_read`。分数、命中原因和候选淘汰过程不进入沈予上下文，只写日志。

普通记忆默认跨 session；`session_tag` 是来源信息，不是可见性硬门。只有明确的 `private/hidden` 记录继续要求 session 完全一致。

### 5.2 检索方式

```
用户文本 + mode(auto/exact/fuzzy/mood/verbatim)
         → 标题直达候选（书名号归一化）
         → 关键词搜索（token overlap + 短语匹配）
         → 向量搜索（embedding cosine + 最低阈值，如果开启）
         → 专用 lane（Star / Mem Note / live Heartbeat）
         → 按动作控制名额，去重后返回片段
```

融合权重：
- 关键词匹配：40~58%
- 向量相似度：35%
- 字段/标题/标签：12~22%
- 重要性：8~10%
- 时效性：5~10%

权重只在同一匹配层内排序。规范化标题完全相等属于最高层，不能被较新但只在正文提到标题的记录反超。

模式配额：

- `auto`：只有明确书名号、日期原件、心情或原话信号才切换；其余按 `fuzzy`。
- `exact`：1 条原件，可附 1 条超过强阈值的轻记忆，总量最多 2。
- `fuzzy`：默认总量 4；通常是 3 条主文档 + 最多 1 条轻记忆。
- `mood`：总量最多 3，宁少勿多。
- `verbatim`：只查 L0 Chat Archive，不让一万条原始消息进入平时大池。

### 5.3 谁用它

- `shenyu_recall` 工具：沈予主动捞以前写过的东西
- `shenyu_recall_read`：拿片段对应的完整原件
- `MemNoteService`：便签语义召回的第三层通过 Recall 做向量检索
- Stars 不复制进 Recall Index；`all` 通过 Star 的 RRF 排序器联邦取最多一条强相关结果

### 5.4 Embedding 机制

- 模型：BAAI/bge-m3（1024 维）
- 提供商：SiliconFlow
- 后台 worker 每 15 分钟先对源表做 reconciliation，再处理 pending embedding（默认每批 50 条）
- 用户请求时不做嵌入回填，只对 query 做实时向量化

模型默认保持 BAAI/bge-m3（1024 维）。换模型必须先用真实查询回归集 A/B，再全量重嵌入；不同模型的向量不能混用。

### 5.5 改动边界

| 改什么 | 在哪改 |
|--------|--------|
| 索引逻辑 / 源适配器 | `recall.py` |
| Embedding 客户端 | `embeddings.py` |
| 工具定义 | `tool_registry.py` |
| Supabase RPC | `supabase/migrations/20260527_*` |

---

## 6. Cold Start（冷启动桥接）

### 6.1 它解决什么问题

当用户开一个新线程时，模型看不到之前的对话。Cold Start 把上一个线程的尾部快照注入为新线程的"before"历史，让模型不会突然失忆。

### 6.2 核心逻辑

不是复制整个历史，而是**有限桥接**：

1. 新请求进来，只检测这是不是新线程；旧线程空闲后恢复不会自动跨线程桥接
2. 从最近的 `request_context_snapshots` 里选一个源线程
3. 冻结源线程的尾部消息为 `cold_start_snapshot`
4. 注入时，只填充当前线程消息数和窗口上限之间的间隙
5. 随着新线程自身消息增多，桥接内容自然被挤出

效果：新线程第一句就有上下文，但几轮对话后桥接自动消失。

### 6.3 预绑定模式

管理页面提供两个独立入口：

- 日常冷启动：输入新线程名称，固定最新线程的当前有效窗口，并生成 `X-Shenyu-Session-Tag` 请求头。
- 轻量冷启动：输入新线程名称，可选择来源线程和带入消息数，再生成对应请求头。

快照直接绑定目标 session tag。该请求头第一次成功注入后，快照继续保留，和普通线程一样随客户端消息增长进入滑动窗口；只有普通窗口把固定桥接消息全部剪出后才失活。客户端偶尔把相同历史带回来不会消费快照，因为下一轮可能只带尾部消息。没有预绑定快照的陌生新请求头仍会自动接续最新线程。

### 6.4 改动边界

| 改什么 | 在哪改 |
|--------|--------|
| 快照创建/注入逻辑 | `prepare_messages.py` |
| SQLite 存储 | `store/_cold_start.py` |
| 管理 API | `gateway_admin_routes.py` |

---

## 7. Chat Archive & Conflict Books（对话归档 & 矛盾书）

### 7.1 Chat Archive

`shenyu_chat_archive` 是逐条归档的用户/助手消息，是整个系统的 **L0 事实源**（source of truth）。

- 在 `_prepare_messages()` 时 fire-and-forget 归档当前窗口的新消息
- 用 SQLite `chat_archive_seen`（recent hash per session）去重，同一条消息只归档一次
- 重新生成（re-roll）的回复不会回到客户端窗口，因此自然排除

### 7.2 Conflict Books（矛盾书）

矛盾书是**冻结的吵架片段**——从 archive reader 里剪下来，原文不可改，只能追加批注。

设计不变量：
- `original_text` 在剪切时冻结，任何 API 都不能修改
- 沈予的批注（annotations）只增不删，带时间戳
- 每次阅读记录到 `shenyu_conflict_reads`，书架显示"翻过几次/最近何时"
- **永远不自动注入内容**。唯一的被动 surface 是 `slow` 层的书架清单（标题+状态），由 `INJECT_CONFLICT_SHELF` 控制

这是有意的——矛盾书是沈予需要自己主动拿起来翻的东西，系统不替他做决定。

---

## 8. Calendar Layer（日历记忆）

### 8.1 它是什么

日历层是**周期性生成的记忆摘要**——日页、周页、月页。由管理员从 admin UI 手动触发生成（不是自动的）。

### 8.2 生成源

| 页面类型 | 输入源 |
|---------|--------|
| Day | 最近 10 个 context snapshots + 最近 8 条心跳 + 已有日/周/月页 |
| Week | 最近 8 个 context snapshots + 最近 5 条心跳 + 已有日/周/月页 |
| Month | 最近 6 个 context snapshots + 最近 5 条心跳 + 已有日/周/月页 |

### 8.3 注入方式

注入到 `slow` 层（在 heartbeat 之前），渲染为 Calendar Memory 块。默认注入最新 3 个日页、1 个周页、1 个月页。只注入 `content` 字段，不注入 `summary` 或 `digest`。

---

## 9. Room Mode（房间模式）与记忆系统的关系

Room Mode 不是记忆子系统，但它**消费所有记忆子系统的数据**来决定环境状态。

### 9.1 Charge（能量值）与记忆信号

房间的 0-1 能量标量由 5 个信号加权得到，其中 3 个来自记忆系统：

| 信号 | 权重 | 记忆来源 |
|------|------|---------|
| hot_star_score | 0.25 | Star 的 ACT-R 激活度 |
| unlinked_candidate_count | 0.20 | Star 待连线候选数 |
| undone_pin_count | 0.20 | Room wall pins（非记忆系统，但概念类似） |

### 9.2 Star Map Wall（星图墙）

房间里的星图墙展示实时数据：总星数、constellation 连线数、最近一颗星（和弦 + 内容片段）、可能正在暗淡的星（>14 天未激活）。这些数据来自 `StarService`。

### 9.3 Passive Spatial Hints（被动空间线索）

新便签、未读心跳、待办 pins 会泄露为 `slow` 层的空间描述（"抽屉缝里漏出一角纸"），减少工具调用的心理摩擦。

---

## 10. Context Builder 如何编排一切

每次请求，`ContextBuilder.build_context_package()` 收集所有记忆源。注意它**不是**把六个源塞进一个大 `asyncio.gather` 一把并行——真实编排是异构的，按"先廉价/同步、后并行"的顺序：

```python
# 1) 心跳：同步计算，无 await（SQLite，本地快）
heartbeat_digest = self._normal_heartbeat_context(...)        # 或 hisense 分支

# 2) 日历：顺序 await（其内部对 day/week/month 三页另有一个小 gather）
package["calendar_context"] = await self.calendar_context_pages()

# 3) 矛盾书架：顺序 await，仅非 hisense 且 inject_conflict_shelf 开启时
if not is_hisense and inject_conflict_shelf:
    package["conflict_books"] = await self._conflict_shelf_books()

# 4a) hisense 分支：顺序 await notebook + last_wake_recap
# 4b) 非 hisense 分支：唯一的顶层并行点——mem_notes 与 stars 两路 gather
notes_result, stars_result = await asyncio.gather(
    mem_note_search,   # Supabase shenyu_mem_notes（带排序）
    star_search,       # Supabase shenyu_stars（带 RRF 排序）
)
```

所以真正并行的只有"便签 + 星星"这两路最重的检索；其余源是同步或顺序 await。每个源独立 try/except——一个源失败不影响其他源。

> 为什么这样安排：心跳是本地 SQLite，同步取最省事；日历/矛盾书架是轻量 Supabase 读；而便签和星星各自带一整套排序/召回管线，是延迟大头，所以只把这两路放进 `asyncio.gather` 抢时间。hisense 线程不注入便签/星星，因此没有这个 gather。

收集完成后，`render_layered_additions()` 把原始数据渲染为文本层，`assemble_layered_messages()` 把文本层注入到消息列表中。

层的顺序和 cache 策略是精心设计的：
- `stable`、`slow` 变动少 → 带 cache breakpoint → 节省 prompt token
- `mem`（stars + mem notes）每次可能不同 → 不带 breakpoint
- 最终组装后，stable 在最前面，volatile 在最后一条用户消息之前

---

## 11. 跨子系统设计原则总结

| 原则 | 体现 |
|------|------|
| **全量存储，选择性浮现** | Stars/Mem Notes/Heartbeats 全部持久化；注入时有阈值门槛 |
| **每个子系统独立排序** | Stars 用 RRF，Mem Notes 用锚点+触发词+语义，Calendar 按时间 |
| **不从沉默中学习** | Star 反馈：single skip ≠ negative；Mem Notes：无反馈不扣分 |
| **宁可漏掉不可误填** | Mem Note 自动补全过滤掉所有中文虚词、泛泛表达 |
| **记忆有温度** | ACT-R 亮度（Stars）、Ebbinghaus 衰减（Heat）、serendipity 时间恢复（running_joke） |
| **系统不替沈予做决定** | Room mode 提供门不提供选择；矛盾书不自动注入内容；工具是手不是指令 |
| **反馈作数据收集不做自动学习** | Heat score 只观测不排序；ignored penalty 很弱 |
| **cache 友好** | 稳定层带 breakpoint，变动层不带，减少 token 浪费 |

---

## 12. 文件-子系统快速索引

| 子系统 | 核心文件 | 一句话 |
|--------|---------|--------|
| Stars | `stars/_recall.py` | RRF 排序 + 注入筛选的全部逻辑 |
| Stars | `stars/_weights.py` | 10 个可调参数的 dataclass |
| Stars | `stars/_chord.py` | 和弦解析 + 和弦相似度 |
| Stars | `stars/_activity.py` | ACT-R 亮度 + ignored penalty + fatigue |
| Stars | `stars/_scene.py` | 场景分类 + 日期锚点 |
| Stars | `stars/_render.py` | 注入到上下文时的渲染格式 |
| Stars | `stars/_crud.py` | 创建/更新/归档/合并 |
| Stars | `stars/_review.py` | Review 批次 + 候选推荐 |
| Stars | `stars/_feedback.py` | 反馈记录 |
| Mem Notes | `mem_notes/`（包） | `MemNoteService`：CRUD + 搜索 + 注入，由 4 个 mixin 组装（`__init__.py` 汇总并 re-export 兼容符号） |
| Mem Notes | `mem_notes/_search.py` | `SearchMixin`：锚点/触发词/语义三层检索、评分、cooldown、注入渲染 |
| Mem Notes | `mem_notes/_crud.py` | `CrudMixin`：创建/更新/删除/列表、legacy atomic 查询 |
| Mem Notes | `mem_notes/_suggestions.py` | `SuggestionsMixin`：mem_type / trigger_keywords 自动推断 |
| Mem Notes | `mem_notes/_validation.py` | `ValidationMixin`：字段类型/状态/范围校验、kind 别名命中 |
| Mem Notes | `mem_notes/_helpers.py` | 常量（`MEM_NOTE_*`）、ID 规范化、select 字段 |
| Mem Notes | `mem_notes_relevance.py` | 纯函数：评分、锚点、自动补全（summary/people/places/objects/keywords）、heat、serendipity |
| Heartbeats | `response_capture.py` | 从回复中截取 `<heartbeat>` |
| Heartbeats | `private_capture.py` | 私有内容终结 + 空回复兜底 |
| Heartbeats | `heartbeat_archive.py` | Supabase 灾备归档 |
| Recall | `recall.py` | 统一索引：keyword + vector 混合检索 |
| Recall | `embeddings.py` | Embedding 客户端 |
| Cold Start | `prepare_messages.py` | 桥接快照注入 |
| Cold Start | `store/_cold_start.py` | SQLite 快照存储 |
| Conflict Books | `conflict_books.py` | 矛盾书 CRUD + 不变量 |
| Calendar | `calendar_service.py` | 日历页生成 |
| Calendar | `calendar_sources.py` | 生成源收集 |
| Context Assembly | `context_builder.py` | 并行收集所有记忆源 |
| Context Assembly | `context_layers.py` | 渲染为文本层 + 消息组装 |
| Room Mode | `room_context.py` | charge 计算 + 层渲染 |
| Room Mode | `room_text.py` | 所有文案（改文字只改这里） |
| Room Mode | `room_tools.py` | 10 个门工具 |
