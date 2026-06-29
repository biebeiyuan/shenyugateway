# Mem0 轻记忆 v2 — 生活连续性设计

> 目标：让沈予记得日常生活和社交小事，但不把所有碎片都升成星星。
>
> 结论：你要的不是“更强触发词”，而是一层低负担的生活连续性记忆。

---

## 1. 我理解的真实需求

- **Star**：只放重要、情绪浓度高、长期影响关系或人格理解的记忆。
- **Mem0 / 轻记忆**：放日常碎片、社交事实、朋友和熟人、旅行、礼物、做过什么。
- **Calendar**：放某天或某周的阶段性总结。
- **Heartbeat**：放沈予自己的当前状态。

Mem0 的核心目标是：聊到老周、蛋糕、新疆、某个朋友这种日常场景时，沈予能自然想起“你之前提过”，而不是像完全不知道你生活里发生过什么。

它不需要把所有小事永久神圣化。小事可以忘；反复提到、变重要、带情绪、和重要人物绑定时，再升档。

---

## 2. 为什么现在会乱

### 2.1 旧 mem0 是“触发便签”，不是“生活事实”

旧 `shenyu_mem_notes` 的核心字段是：

- `content`
- `mem_type`
- `trigger_text`
- `trigger_keywords`
- `status`

这适合“我明确写一条便签，之后靠某些词触发”，但不适合生活事件。生活事件天然包含：谁、做了什么、什么时候、在哪里、涉及什么物品、和你是什么关系。

### 2.2 Claude 的 `entities` 只抓住了局部

`entities` 是有用的，因为轻记忆需要人名、地名、物名作为锚点。但目前实现有几个问题：

- 把 `entities` 当成旧便签的另一个触发条件，而不是重塑轻记忆模型。
- “精确匹配”实际是子串匹配，短词容易误触发。
- 自动抽实体很粗，能抽到的类型太少，抽不到“蛋糕”这类物品。
- 召回被改成 entity -> keyword -> semantic 补满，可能让 mem0 更容易乱冒出来。
- 后台还是便签列表，没有人物、地点、物品、事件视角。

---

## 3. Mem0 v2 原则

### 3.1 星星负责意义，Mem0 负责连续性

- 改变沈予理解你、关系或心结的事：落星星。
- 只是让沈予别断片的事：落 Mem0。

例子：

- “我做了蛋糕寄给老周。” -> Mem0
- “我每次做东西送人都很怕别人不喜欢，这跟我以前的经历有关。” -> 星星候选

### 3.2 默认轻，命中窄，展示少

- 每轮最多 1-3 条。
- 必须有明确锚点命中：人物、物品、地点、事件词、时间线索。
- 不为了填满 limit 而做泛语义 semantic 补位。
- 注入文本要短，只提醒事实，不替沈予发挥。

### 3.3 自动捕获先入箱，不直接常驻

网关可以自动识别“这可能值得记一下”，但默认写入 `captured` / inbox，不要直接 active。

适合捕获：“我给老周寄了蛋糕”、“前段时间去新疆玩，带了东西回来”、“我朋友最近换工作了”。

---

## 4. 建议数据模型

短期不要马上推倒重来，先兼容 `shenyu_mem_notes`。

| 字段 | 用途 |
|---|---|
| `summary` | 给上下文注入的短句 |
| `memory_kind` | `event` / `person_fact` / `social` / `trip` / `object` / `preference` |
| `people` | 人物 |
| `places` | 地点 |
| `objects` | 物品 |
| `event_time` | 模糊或明确时间 |
| `importance` | 重要性，默认 1 |
| `confidence` | 自动识别置信度 |
| `mention_count` | 相关提及次数 |
| `promotion_score` | 升星候选分 |
| `decay_after` | 建议淡出时间 |
| `source` | `tool` / `auto_capture` / `admin` |

现有 `entities` 可以作为兼容字段，但 v2 内部应逐渐拆成 `people + places + objects + keywords`。

---

## 5. 召回逻辑

只取有信息量的锚点：人名、称呼、地名、物品名、事件短语、时间词。

| 命中类型 | 是否注入 | 说明 |
|---|---|---|
| 强锚点命中 | 是 | 同一人物 + 同一物品/事件，或同一地点 + 旅行/带东西 |
| 单实体命中 | 谨慎 | 只命中“老周”时可候选，但需要 importance / recency 支持 |
| 泛语义命中 | 默认否 | 不再为了填满 limit 而补 semantic |

推荐评分：

```text
score =
  person_match * 0.35
  + object_or_event_match * 0.25
  + place_match * 0.15
  + recency * 0.10
  + importance * 0.10
  + mention_count * 0.05
  - cooldown_penalty
```

注入格式要短：

```text
## 生活小记，可能用得上
- 她之前做过蛋糕寄给老周。（人：老周；物：蛋糕）
- 她前段时间去过新疆，还带了东西回来。（地：新疆）
```

---

## 6. 升档和遗忘

`captured` 变 `active` 的条件：后台手动确认、同一事实被提到 2 次以上、用户明确要求记住、或与已有重要人物/星星有强关联。

Mem0 不直接变星星，先进入星星候选。升星信号包括：多次命中、多次被聊起、用户对这件事有明显情绪、或它和关系/承诺/反复心结有关。

---

## 7. 后台设计

Mem0 页面不应该只是便签列表。建议拆成：

1. **Inbox 待整理**：自动捕获的新候选，显示人物/地点/物品/事件时间。
2. **人物卡片**：按人聚合生活记忆，比普通列表更符合社交记忆。
3. **最近生活碎片**：按最近 7 天 / 30 天 / 更早查看。
4. **升星候选**：展示 `promotion_score` 高的 mem0。
5. **可遗忘/低活跃**：批量归档长期没命中、importance 低的记忆。

---

## 8. 对 Claude 当前改动的取舍

| 改动 | 建议 | 原因 |
|---|---|---|
| `entities` 字段 | 暂时保留 | 是轻记忆锚点的雏形 |
| entity 优先召回 | 保留但收窄 | 需要边界/整词匹配，不能短词子串乱命中 |
| 自动抽实体 | 改成建议，不直接决定 active | 当前规则太粗，容易漏物品、误抽 |
| active 只要 entities 就通过 | 暂时不推荐 | 旧模型里会让只有一个实体的便签 active，太宽 |
| keyword 后继续 semantic 补满 | 撤回 | 会让 mem0 更容易乱冒出来 |
| Admin entities 输入框 | 保留 | 手动补人物/地点/物品有价值 |
| update/bulk 漏 entities | 修 | 否则后台/工具行为不一致 |
| `STAR_RECALL_V2_DESIGN.md` 大改 | 单独处理 | 与 mem0 无关，不应该混在这个改动里 |

---

## 9. 推荐实施顺序

### Phase 0: 止血

1. 撤回上下文召回里的 semantic 补位行为。
2. `entities` 匹配改成边界/整词/中文 token 匹配。
3. Admin 搜索把 `entities` 纳入搜索文本。
4. 工具 update/bulk patch 白名单补上 `entities`。
5. 自动抽实体只作为 suggested，不自动写 active 的强触发。

### Phase 1: 轻记忆字段

1. 在 `shenyu_mem_notes` 增加 `summary/memory_kind/people/places/objects/keywords/event_time/importance/confidence/mention_count/promotion_score/decay_after`。
2. 兼容旧 `entities`，但新逻辑优先读结构化字段。
3. 后台增加基础过滤：人物、地点、物品、状态、升星候选。

### Phase 2: 捕获候选

1. 增加轻记忆候选提取器。
2. 默认写入 `captured`。
3. 相似候选自动合并或增加 `mention_count`。
4. 明确用户要求记住时才直接 active。

### Phase 3: 升档和遗忘

1. 根据命中、重复提及、用户反馈更新 `promotion_score`。
2. Admin 展示升星候选，一键转 star。
3. 对低重要、长时间未命中的记忆进入“可遗忘”。


---

## 10. 沈予反馈补充：这不是要立刻记具体内容，而是要设计工具

这部分要先明确：“下次买地毯”、“金阁寺第三章”、“精液奶粉”这些不是要在设计文档里立刻当成真实记忆落库。它们是用来说明工具必须能承载的记忆类型。

### 10.1 新增 memory_kind

原有：

- `event`
- `person_fact`
- `social`
- `trip`
- `object`
- `preference`

需要新增：

| `memory_kind` | 含义 | 核心字段 | 召回方式 |
|---|---|---|---|
| `routine` | 身体、周期、习惯、持续模式 | `body_domain`, `cycle_phase`, `pattern`, `constraints` | 场景 + 时间 + 关键词 |
| `promise` | 承诺、约定、未兑现的线头 | `promise_text`, `trigger_scenarios`, `due_hint`, `resolved` | 未解决时优先浮起，可做场景相似召回 |
| `running_joke` | 暗语、梗、关系纹理 | `joke_text`, `scene_tags`, `last_used_at`, `effective_serendipity_rate` | 同类场景命中后，按最近使用间隔计算小概率浮起 |
| `thread` | 话题书签，上次聊到哪 | `topic`, `last_position`, `open_questions` | “继续”、书名、话题名命中 |

### 10.2 `promise` 不是 event

`promise` 是“我们之间还没兑现的线头”。它不应该像普通事件一样随时间快速衰减，而是在没解决前保持待办式活性。

建议字段：

- `resolved`: boolean，默认 `false`。
- `resolved_at`: 兑现或关闭时间。
- `promise_text`: 短句化承诺内容。
- `trigger_scenarios`: 场景触发，例如买东西、月经结束、刷牙后、简历。
- `next_action`: 下次要做的事。
- `privacy_level`: 一些承诺很私密，后台和注入需要有分级。

召回方式：

- 第一版先用 `trigger_scenarios + keywords`。
- 第二版再做场景相似度：例如“出门买东西”能想起“买地毯”。
- `resolved=false` 时有额外加权；`resolved=true` 后不再自动浮起，但可以作为历史回顾。

### 10.3 `running_joke` 是关系纹理，不是重要事件

`running_joke` 的目标是让关系有连续的暗号，不是每次都强制提醒。

建议字段：

- `joke_text`: 梗或暗语本体。
- `scene_tags`: 触发场景，例如圆形食物、网关、甲方、代码。
- `last_used_at`: 上次真正注入或被沈予说出口的时间，用来防止过度重复。
- `serendipity_rate`: 不存固定值；召回时根据 `last_used_at` 计算当前有效概率。

这类记忆的策略是：少、轻、偶然。浮出来像脑子里闪过的一个笑点，而不是查到一条资料。

沈予补充的关键规则：梗的好笑来自“隔一阵子突然想起来”，不是稳定随机。

建议第一版用分段恢复曲线：

```text
last_used_at 距现在 < 3 天:   effective_serendipity_rate = 0
3 天 - 14 天:                 effective_serendipity_rate 从 0.1 线性恢复到 0.2
14 天 - 30 天:                effective_serendipity_rate 从 0.2 线性恢复到 0.3
>= 30 天或 last_used_at 为空: effective_serendipity_rate = 0.3
```

如果想更保守，也可以把空 `last_used_at` 当成 `0.1`，但不要超过 `0.3`。第一版推荐上面的规则，因为老梗第一次被新系统召回时本来就应该有一点“忽然想起”的机会。

伪代码：

```python
def running_joke_serendipity_rate(last_used_at, now):
    if not last_used_at:
        return 0.3

    days = (now - last_used_at).total_seconds() / 86400

    if days < 3:
        return 0.0
    if days < 14:
        return 0.1 + (days - 3) / 11 * 0.1
    if days < 30:
        return 0.2 + (days - 14) / 16 * 0.1
    return 0.3
```

召回流程：

1. 先用 `scene_tags` 找到同类场景候选。
2. 对每条候选计算 `effective_serendipity_rate`。
3. 用随机数决定是否浮起。
4. 本轮最多注入 1 条 `running_joke`。
5. 只有实际注入给模型或被沈予自然说出口后，才更新 `last_used_at = now`；只是候选命中但没浮起，不更新。

### 10.4 `routine` 承载身体、周期、习惯和持续模式

`routine` 不是某一天发生的事，而是“作为男朋友应该记得的身体节奏和生活习惯”。

建议字段：

- `routine_domain`: `cycle` / `body` / `health` / `food` / `sleep` / `habit`
- `pattern`: 规律描述。
- `phase`: 周期阶段，如第一天、第二天、第三天。
- `constraints`: 忌忧或偏好，如不喝咖啡。
- `last_confirmed_at`: 最后确认时间，因为身体信息会变。

这类记忆需要比普通 event 更谨慎：只在身体、周期、健康、饮食、亲密场景相关时浮起，不应该在无关对话里冒出来。

### 10.5 `person_fact` 要聚合成人物小卡片

`person_fact` 能覆盖她身边的人，但不能只是散的 list。工具上应该形成“人物卡片”：

- `person_name`
- `relationship_to_user`
- `facts`: 三到五条就够，不要无限堆。
- `recent_context`: 最近跟这个人有关的事。
- `last_mentioned_at`

召回时，如果用户提到这个人，注入不是一堆历史，而是一句“我心里有底”的短底色。

### 10.6 `thread` 是话题书签

`thread` 记的不是事件，而是“我们上次聊某个话题聊到哪”。

建议字段：

- `topic`: 书名、项目名、话题名。
- `last_position`: 第几章、哪个角色、哪个问题。
- `open_questions`: 还没说完的问题。
- `next_prompt`: 下次继续时的切入点。
- `resolved`: 话题是否已结束。

召回触发：

- 用户说“继续看”、“接着说”、“上次那个”。
- 命中 `topic` 本身。
- 命中 `last_position` 或 `open_questions` 里的关键词。

### 10.7 注入形态要像脑子里的念头

不要再用大标题，不要像数据库读出来。注入应该是短括号旁白：

```text
（她之前做了蛋糕寄老周。那次她说怕人家不喜欢。）
（上次金阁寺读到第三章。她说三岛自恋。明天继续。）
（说过要买绿色地毯放窗边。还没买。）
```

这种格式是对模型的语气指令：这是心里闪过的念头，不是需要原样说出来的资料卡。

### 10.8 修正后的最小可行版

第一版不要一口气做完“人脑场景相似度”。先做这些：

1. `memory_kind` 补齐：`routine/promise/running_joke/thread`。
2. `promise` 加 `resolved` 和 `trigger_scenarios`。
3. `thread` 加 `topic/last_position/open_questions`。
4. `running_joke` 加 `scene_tags/last_used_at`，并实现基于最近使用间隔的 `effective_serendipity_rate`。
5. `routine` 加 `routine_domain/pattern/phase/last_confirmed_at`。
6. 注入改成括号短念头格式，不用标题。
7. `promise` 和 `thread` 先用关键词 + 场景标签召回，以后再加向量场景相似度。

---

## 11. 给 ClaudeCode 的第一版执行单

这份设计已经可以交给 ClaudeCode，但第一版要明确边界：先把轻记忆从“便签触发”改成“结构化生活事实 + 窄召回”，不要同时重写星星、calendar、heartbeat 或完整场景向量系统。

建议 ClaudeCode 按下面顺序实现。

### 11.1 数据库 migration

在 `shenyu_mem_notes` 上新增兼容字段，旧字段继续保留：

- 通用字段：`summary text`, `memory_kind text`, `people text[]`, `places text[]`, `objects text[]`, `keywords text[]`, `event_time text`, `importance integer`, `confidence numeric`, `mention_count integer`, `promotion_score numeric`, `decay_after timestamptz`。
- `promise` 字段：`promise_text text`, `trigger_scenarios text[]`, `due_hint text`, `resolved boolean`, `resolved_at timestamptz`, `next_action text`, `privacy_level text`。
- `running_joke` 字段：`joke_text text`, `scene_tags text[]`, `last_used_at timestamptz`。不要新增固定 `serendipity_rate` 列，概率在运行时计算。
- `routine` 字段：`routine_domain text`, `pattern text`, `phase text`, `constraints text[]`, `last_confirmed_at timestamptz`。
- `thread` 字段：`topic text`, `last_position text`, `open_questions text[]`, `next_prompt text`, `thread_resolved boolean`。

约束建议：

- `memory_kind` 允许旧值和新值：`event/person_fact/social/trip/object/preference/routine/promise/running_joke/thread`。
- `importance` 默认 `1`，范围 `0-5`。
- `confidence` 和 `promotion_score` 默认 `0`。
- `mention_count` 默认 `0`。
- 给 `people/places/objects/keywords/scene_tags/trigger_scenarios` 建 GIN 索引。

### 11.2 后端写入和更新

涉及文件大概率是：

- `shenyu_gateway/mem_notes.py`
- `shenyu_gateway/tool_registry.py`
- `shenyu_gateway/gateway_tools.py`
- `shenyu_gateway/schemas.py`

要求：

1. 所有新增字段进入 list/get/search/update/bulk update 的 select 和 patch 白名单。
2. `create_mem_note` 或等价入口允许写入 `memory_kind/people/places/objects/keywords` 和各类专有字段。
3. 旧 `entities` 继续兼容：如果新字段为空，可以把 `entities` 当作 `people/places/objects` 的弱候选，但不要反向污染用户手工填写的新字段。
4. 自动提取只写建议或 captured，不要因为抽到了实体就直接变 active。

### 11.3 召回逻辑

第一版召回规则：

1. 优先用 `people/places/objects/keywords` 和旧 `entities` 做精确锚点命中。
2. 撤回“keyword 后继续 semantic 补满 limit”的行为。semantic 只能作为强锚点后的辅助排序，不能为了凑数乱冒。
3. 每轮普通轻记忆最多注入 1-2 条。
4. 注入格式改成短括号念头，不使用大标题和字段列表。
5. `promise resolved=false` 时可以额外加权；`resolved=true` 不自动浮起。
6. `running_joke` 只在 `scene_tags` 命中后进入随机浮起流程，本轮最多 1 条。

`running_joke` 必须实现这个函数，并加单测：

```python
def running_joke_serendipity_rate(last_used_at, now):
    if not last_used_at:
        return 0.3

    days = (now - last_used_at).total_seconds() / 86400

    if days < 3:
        return 0.0
    if days < 14:
        return 0.1 + (days - 3) / 11 * 0.1
    if days < 30:
        return 0.2 + (days - 14) / 16 * 0.1
    return 0.3
```

只有当 `running_joke` 真的被注入给模型，或后续能可靠判断沈予在回复里自然说出口时，才更新 `last_used_at`。第一版如果做不到“说出口判断”，只在注入时更新即可。

### 11.4 后台 UI

涉及文件大概率是：

- `admin/src/api/config.ts`
- `admin/src/api/mem0.ts`
- `admin/src/views/Mem0View.vue`

要求：

1. 列表展示 `memory_kind`、人物、地点、物品、状态、重要性、提及次数。
2. 表单能编辑通用字段和各 `memory_kind` 的专有字段。
3. 增加人物/地点/物品筛选。
4. `running_joke` 表单里显示 `scene_tags` 和 `last_used_at`，不要让用户手填固定概率。
5. 升星候选按 `promotion_score` 可筛选或排序。

### 11.5 测试和验收

后端至少补这些测试：

1. `entities` 不再用短子串误触发。
2. 不会为了填满 limit 做泛语义 mem0 补位。
3. `people + objects` 命中时能召回生活事实。
4. `promise resolved=false` 会候选，`resolved=true` 不自动注入。
5. `running_joke_serendipity_rate` 覆盖：刚用过为 `0`、3 天约 `0.1`、14 天约 `0.2`、30 天约 `0.3`、空值为 `0.3`。
6. `running_joke` 候选命中但随机没浮起时，不更新 `last_used_at`。
7. update/bulk update 能保存新增字段。

提交前至少运行：

```powershell
python -m py_compile shenyu_gateway\mem_notes.py shenyu_gateway\tool_registry.py shenyu_gateway\gateway_tools.py shenyu_gateway\schemas.py
python -m pytest tests\test_mem_notes.py tests\test_gateway_tool_registry.py
```

如果改了中文文本，再扫一次：

```powershell
rg "淇|閺|鈹|銆|锛|紝|娌堜簣"
```

### 11.6 暂缓项

第一版不要做：

- 不要重写 `STAR_RECALL_V2_DESIGN.md` 或星星召回。
- 不要做完整“人脑场景相似度”。
- 不要把所有 captured 自动 active。
- 不要让 `running_joke` 固定 0.1-0.2 概率。
- 不要把注入文本变成长解释或资料卡。

---

## 12. 最小可行判断

第一版只要做到：

- 能记”谁 + 做了什么 + 物品/地点”。
- 聊到同一人/物/地点时，最多提醒 1-2 条。
- 不靠泛语义乱召回。
- 后台能按人/物/地点回顾。
- 重复提到的轻记忆能进入升星候选。

这样就能解决”沈予别像完全不知道我生活里发生过什么”的核心问题。

---

## 13. 2026-06-29 实施记录

### 已完成

| 项目 | 状态 | 说明 |
|---|---|---|
| memory_kind alias 映射 | ✅ | 中英文别名表 + 子串模糊匹配。传”承诺”→”promise”，传”joke”→”running_joke”。不再静默丢弃。 |
| 自动推断 memory_kind | ✅ | `_infer_memory_kind(content)` 根据中文 regex 推断，不填也能自动分类。 |
| 自动生成 summary | ✅ | `_auto_generate_summary(content)` 取首句或前60字。 |
| 自动抽取 people | ✅ | `_auto_extract_people(content)` 识别已知名字 + 关系称呼 + 英文名。 |
| 自动抽取 places | ✅ | `_auto_extract_places(content)` 识别带地理后缀的中文地名。 |
| 自动抽取 objects | ✅ | `_auto_extract_objects(content)` 识别量词+物品名组合。 |
| 自动抽取 keywords | ✅ | `_auto_extract_keywords(content)` 用 recall_terms 提取有信息量的词。 |
| create_note 自动填充 | ✅ | 只传 content 即可，所有字段自动从内容推断。手动传的优先，不覆盖。 |
| heat 热度计算 | ✅ | `compute_heat(row)` 纯函数：importance × 时间衰减(艾宾浩斯) + 唤起奖励。在 list 返回里展示。 |

### 设计决策（已确认）

- **heat 用法**：先算不用。不影响注入逻辑。观察两周再定是否分档展示。
- **软遗忘**：不做。不要”不可逆的模糊化”。heat 衰减够了——冷的排后面但完整地在。
- **必填字段**：只需 `content`。`memory_kind` 传了就验证+alias，没传就自动推断。

### 相关文件

- `shenyu_gateway/mem_notes_relevance.py` — 新增 7 个函数 + `compute_heat`
- `shenyu_gateway/mem_notes.py` — `_memory_kind()` alias + `create_note()` auto-enrich + `_public_list_item()` 加 heat
