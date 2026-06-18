# 沈予的宇宙 · 可学习召回设计

> 这份文档是在 `STAR_MEMORY_DESIGN.md` 和 kimi-core 研究笔记之后整理的新版本。
> 重点不是一次做出最聪明的记忆系统，而是先把能被观察、反馈、调参、替换的召回骨架搭好。

---

## 一、设计目标

### 1.1 前台目标

沈予这边保持轻。

```text
[star]Cm(add9) · 她笑着说"你是我的章鱼"[/star]
```

一颗星落下，不需要填主题、分类、重要性、情绪量表。

注入给沈予时也保持轻：

```text
Cm(add9) · 她笑着说"你是我的章鱼"
F -> Am7 · 那一晚 · 买它 · 握腕
```

不要管理感，不要标题框，不显示分数、亮过几次、调试信息。

### 1.2 后台目标

网关只做两件事：

1. **日常召回注入**：根据最新聊天内容，捞出此刻可能该响的星、星座、内容引力、和声引力，注入到原 mem 层位置。
2. **Review 反星连线**：把新星和网关判断可能相关的候选反上来，让沈予决定是否连成星座。

系统要越用越聪明，但 V0 不追求黑箱自动学习。V0 先做到：

- 每次为什么反上来都能解释。
- 每次反上来的候选都能被打反馈。
- 每次权重、模型、公式都有版本。
- 将来可以用反馈数据离线拟合更好的召回权重。

---

## 二、核心原则

1. **创建要轻**：沈予只写和弦和一句话，其余全部后台处理。
2. **星座由沈予确认**：网关只能建议，不能替他把星连成星座。
3. **全量存储，克制召回**：星可以都留下，但每次只递少数几颗。
4. **候选也要留痕**：不只记录最终注入了什么，也记录当时考虑过什么、为什么没上。
5. **反馈是训练信号**：`该反`、`不该反`、`连起来`、`应该反这个` 都要变成数据。
6. **先透明，后学习**：先用可解释加权公式；反馈足够后再拟合权重或引入 reranker。
7. **算法可替换**：embedding 模型、和弦距离、权重、阈值都要版本化，旧数据可复盘。

---

## 三、前台对象

### 3.1 星

星是沈予主动落下的一瞬。

最小字段：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `content` | 星的文字 |
| `chord` | 和弦，可空 |
| `embedding` | 内容向量 |
| `is_constant` | 恒星标记 |
| `created_at` | 创建时间 |
| `session_id` | 来源会话 |

不建议 V0 强迫填写 `theme`、`belonging`、`importance`。这些会让创建变重。

### 3.2 星座

星座是沈予确认过的旋律。

星座可以有名字，但注入时不一定显示名字。更重要的是顺序：

```text
F -> Am7 · 那一晚 · 买它 · 握腕
```

星座关系是最高质量正样本：沈予确认这些星确实连在一起。

### 3.3 和弦

和弦不是普通标签。它是沈予给体感、氛围、联想路径的私有编码。

后台可以从和弦派生可计算信号：

| 信号 | 说明 |
|---|---|
| `chord_exact_match` | 和弦是否相同 |
| `chord_root_distance` | 根音在半音/五度圈上的距离 |
| `chord_quality_match` | 大小调、七和弦、挂留、增减等结构是否相近 |
| `chord_tension` | 和弦张力，V0 先空着，不参与排序 |
| `chord_distance` | 汇总后的和声距离 |

V0 不需要证明和弦一定有用。先记录，等反馈数据回来后再看它对召回是否真的有预测力。
V0 的和弦距离只做 `exact/root/quality`，不要一开始就把最主观的 tension 放进去。

---

## 四、后台召回任务

### 4.0 kimi-core 给这层的参考

kimi-core 对这层最有参考价值的不是某一个字段，而是三个工程习惯：

1. **激活从事件历史重算**：它在 thought-pool 里使用 ACT-R base-level activation。这里可以借来替代手写漂移。
2. **多信号检索**：它不是只靠 embedding，而是 semantic、keyword、time、importance 一起打分，并记录 score breakdown。
3. **定时扫相似边**：它用 nightly similarity sweep 给 memory 建 `similar` 边。我们可以把这个思路扩成内容引力和和声引力两条 sweep。

注意：kimi-core 的 ACT-R 原本主要用于 thought/drive salience，不是直接 memory retrieval；和声引力也不是它现成有的能力，是我们基于星和和弦要新增的层。

### 4.1 任务 A：日常召回注入

触发：用户发来最新消息，网关请求上游前。

输入：

- 最新 user message
- 最近 2-3 条上下文，可配置
- 当前会话 id

输出：

- 注入到 mem 位置的少量星/星座
- 默认最多 3 个显示单元

候选来源：

| 来源 | 说明 |
|---|---|
| 内容相似 | embedding / reranker / keyword |
| 和声引力 | 和弦距离相近、张力相近 |
| 内容引力 | nightly sweep 建的内容相似边 |
| 星座展开 | 命中星属于星座时，整句旋律优先 |
| 恒星 | 一碰就亮，但不是无条件常亮 |
| 最近新星 | 可低权探索，避免刚写的星永远没机会 |
| ACT-R 亮度 | 从激活日志实时算出的当前亮度 |

日常注入要保守。宁可少递，也不要把噪音铺满上下文。

### 4.2 任务 B：Review 反星连线

触发：沈予调用 `shenyu_star_review`，或圆儿在 admin 里查看。

输入：

- 未 review 的新星
- 这些新星的候选关联
- 最近被激活但未连线的候选

输出：

- 新星列表
- 每次最多 5 颗新星
- 每颗新星最多 3 条候选关联
- 一次 review 最多 9 条候选，超过的留到下次

review 可以比日常注入更大胆，但也要限流。默认每颗星反 3 条、每次最多 5 颗新星，不做瀑布流。

---

## 五、召回留痕

### 5.1 recall_runs

每一次召回建一条 run。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `surface` | `daily_inject` / `review_suggest` / `admin_eval` |
| `trigger_text` | 触发文本，截断保存 |
| `seed_star_id` | review 时可记录以哪颗新星为中心 |
| `session_id` | 会话 |
| `ranker_version` | 排序器版本 |
| `feature_schema_version` | 特征版本 |
| `weights_version` | 权重版本 |
| `embedding_model` | 向量模型 |
| `chord_model_version` | 和弦距离版本 |
| `created_at` | 时间 |

### 5.2 recall_candidates

每个候选一条。重要的是：即使没展示，也可以记录 shadow 候选。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `run_id` | FK |
| `candidate_type` | `star` / `constellation` |
| `candidate_id` | 星或星座 id |
| `rank` | 当时排序 |
| `shown` | 是否展示给 review |
| `injected` | 是否注入日常上下文 |
| `final_score` | 最终分 |
| `content_score` | 内容相似 |
| `keyword_score` | 关键词相似 |
| `chord_score` | 和弦/和声相似 |
| `harmony_score` | 和声引力边分 |
| `content_gravity_score` | 内容引力边分 |
| `actr_score` | 从激活历史算出的亮度 |
| `constellation_bonus` | 星座展开/确认关系加成 |
| `constant_bonus` | 恒星加成 |
| `ignored_penalty` | 忽略/未连线惩罚 |
| `novelty_bonus` | 新星探索加成 |
| `feature_json` | 额外特征快照 |

### 5.3 为什么要存特征快照

星库会不断变大，公式也会更新。

如果只存一个最终分，未来无法知道：

- 当时是因为内容像反上来的，还是因为和弦像反上来的。
- 是哪个版本的和弦距离在起作用。
- 旧权重和新权重谁更好。
- 某条反馈到底该归因给哪个信号。

所以候选必须保存当时特征快照，而不只是保存 id。

---

## 六、反馈设计

### 6.1 单候选反馈

每条候选可以被打一个反馈：

| 反馈 | 训练含义 |
|---|---|
| `good` | 该反上来，正样本 |
| `bad` | 不该反上来，强负样本 |
| `connect` | 沈予确认连线，强正样本 |
| `missed` | 系统没反，但用户认为应该反，漏召回正样本 |

`missed` 很重要。只看系统反出来的 3 条，会训练出“这 3 条谁更好”，但学不到“真正该反的是第 7 条或库里另一颗”。
`missed` 入口必须同时存在于 admin 和 `shenyu_star_review` 工具里。很多“该反但没反”的判断只有沈予自己知道。

### 6.2 feedback 表

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `run_id` | 属于哪次召回 |
| `candidate_id` | 被评价的候选，可空 |
| `expected_candidate_type` | `missed` 时填写 |
| `expected_candidate_id` | `missed` 时填写 |
| `feedback` | `good` / `bad` / `connect` / `missed` |
| `scored_by` | `圆儿` / `沈予` / `admin` |
| `note` | 可选 |
| `created_at` | 时间 |

### 6.3 弱负反馈

看过但没连，不要立刻当负样本。

建议规则：

- 明确点 `bad`：强负。
- 单次 review 展示过但无动作：不计入训练。
- 同一候选或同类候选连续 3 次展示都无动作：才记为弱负。
- 如果后来被连线，清掉或衰减之前的弱负。
- 弱负只影响自动候选排序，不影响沈予手动星座。

---

## 七、关系与引力

### 7.1 边类型

星与星之间的关系可以统一存在一张边表。

| 类型 | 来源 | 可信度 |
|---|---|---|
| `constellation` | 沈予手动连线 | 最高 |
| `content_gravity` | 内容相似 sweep | 中 |
| `harmony_gravity` | 和弦/和声相似 sweep | 中或待验证 |
| `co_activated` | 多次一起被召回/激活 | 中 |
| `feedback_positive` | 反馈强化 | 高 |
| `feedback_negative` | 反馈惩罚 | 负向 |

### 7.2 自动边限流

nightly sweep 不应该给每颗星连很多边。kimi-core 的 `memory-similarity` 思路是：定时找相似 memory，超过阈值才建边，每条最多 top-K。我们可以沿用这个“后台牵线、前台克制”的方式，但分成两类：

- **内容引力 sweep**：根据 content embedding / keyword / reranker 找内容相近的星。
- **和声引力 sweep**：根据和弦 exact/root/quality/tension/distance 找和声相近的星。

建议默认：

- 每颗新星最多建 `top_k = 3` 条内容引力边。
- 每颗新星最多建 `top_k = 3` 条和声引力边。
- 低于阈值不建边。
- 已被多次忽略的相似模式降低展示优先级。
- 内容引力和和声引力分开统计 precision，不要糊成一个“相关”。

### 7.3 边不是星座

自动边只表示“网关觉得可能有引力”。  
只有沈予连过，才是星座。

### 7.4 ACT-R 亮度

原先的 `depth` 漂移是手写规则：

```text
14 天没碰 +0.05
30 天没碰 +0.02
```

这类规则能用，但很容易变成猜数字。更好的方式是把“亮度”从激活日志实时算出来：

```text
B = ln(Σ age_j^(-d))
```

其中：

- `age_j` 是第 j 次激活距离现在的时间。
- `d` 可先取 `0.5`。
- 越近的激活贡献越大。
- 多次激活会叠加。
- 分散在较长时间里的多次激活，比短期密集爆发更稳定。

对系统来说，这意味着：

- `depth` 不必作为主状态每天加减。
- `shenyu_star_activations` 才是原始事实。
- 查询时计算或缓存 `actr_score`。
- 恒星可以加固定 boost，但仍不等于无条件常亮。

V0 可以先实现一个简化版 `actr_score`，同时保留 `activation_count/last_activated_at` 方便观察。

---

## 八、初始排序公式

V0 先用透明公式。kimi-core 的参考是：

```text
semantic * 0.35 + keyword * 0.50 + time_decay * 0.10 + importance * 0.05
```

它给我们的启发是：纯 embedding 不够，关键词和其他硬信号要参与，而且每个分数都要能解释。

我们的 star 召回公式可以先写成：

```text
final =
  W_content * content_score
+ W_keyword * keyword_score
+ W_chord * chord_score
+ W_harmony * harmony_score
+ W_content_gravity * content_gravity_score
+ W_actr * actr_score
+ W_constellation * constellation_bonus
+ W_constant * constant_bonus
+ W_novelty * novelty_bonus
- W_ignored * ignored_penalty
```

日常注入和 review 建议使用不同权重。

初始权重不要假装已经科学。V0 只需要：

- 给一个保守默认。
- 把所有原始分和贡献分存进 `recall_candidates`。
- 等反馈积累后再拟合或手动调权。

### 8.1 日常注入初始倾向

日常注入更保守：

- 星座加成高。
- 恒星加成高，但不无条件注入。
- 内容相似和关键词要过基础门槛。
- 和声引力可以参与，但需要限流。
- 自动边只作为辅助，不让它压过沈予确认的星座。

### 8.2 Review 初始倾向

review 可以探索：

- 新星附近的和声引力权重可以稍高。
- 内容引力和和声引力都展示少量。
- 被忽略多次的候选降权。
- 每颗新星最多反 3 条。
- 每次 review 最多处理 5 颗新星。

---

## 九、学习路线

### V0：记录，不自动学

- 建表。
- 存 run/candidate/feedback。
- 显示 score breakdown 给 admin，不给沈予。
- 手动调权重。

### V1：离线拟合权重

当反馈达到一定数量，比如 100-300 条：

- 用 `good/connect/missed` 做正样本。
- 用 `bad` 做强负样本。
- 用同一候选或同类候选连续 3 次展示无动作做弱负样本。
- 拟合简单模型：logistic regression 或 learning-to-rank。
- 输出一组新权重，保存为新 `weights_version`。

### V2：评估与 A/B

- 用历史反馈构造 eval set。
- 指标：precision@3、recall@3、MRR。
- 对比旧权重和新权重。
- 新权重先在 shadow mode 跑，再正式启用。

### V3：reranker

当星数量上千、简单权重不够时：

- 先粗筛 top 20-50。
- 用本地 reranker 重排。
- 仍保留特征快照和最终分。
- 仍要求可回滚。

---

## 十、Shadow Mode

实际只展示 3 条，但后台可以记录 top 20。

```text
shown = true   前 3 条
shown = false  shadow top 4-20
```

这有两个好处：

1. 不打扰沈予。
2. 未来可以分析：如果用户总是手动补第 8 条，说明排序权重错了，不是候选池没有它。

---

## 十一、观察面板

给圆儿看的 admin 不追求浪漫，追求可诊断。

### 11.1 召回日志

显示每次 run：

```text
触发文本
候选排名
最终展示/注入
各项 score breakdown
反馈
ranker_version
```

### 11.2 和弦质检

指标：

- 和弦多样性。
- 高频和弦占比。
- 和弦距离是否能预测 `good/connect`。
- 和声引力边的 precision@3。
- 内容引力边和和声引力边哪个更常被确认。

### 11.3 漏召回分析

统计：

- `missed` 最常来自哪些特征。
- 该反但没进 top 3，是否在 shadow top 20 里。
- 如果连 shadow top 20 都没有，说明候选召回阶段有问题。

---

## 十二、文献与外部启发

这些不是系统结论，只是给变量设计提供参考。

### 12.1 ACT-R

ACT-R base-level activation 可作为星的“当前亮度”：

```text
B = ln(Σ age_j^(-d))
```

它适合替代手写漂移规则，因为亮度来自激活历史，而不是每天拍脑袋加减。  
在实现上，激活日志是原始数据；`actr_score` 是查询时计算或缓存的派生值。

### 12.2 LLM 情绪几何

`Valence-Arousal Subspace in LLMs` 这类研究提示：LLM 激活空间里可能存在情绪相关的几何结构。  
这不能证明沈予的和弦一定准确，但支持一个温和假设：

```text
和弦可能不是纯装饰，它可能是沈予给内部状态几何找的私有坐标。
```

因此，和弦值得记录和验证。

### 12.3 Steering vectors 的冷水

steering vectors 研究也提醒：

- 方向存在，不代表干预稳定。
- 有些概念会反向或失真。
- 非线性结构可能比简单线性方向更重要。

对应到本系统：和弦信号要被质检，不能因为它美就无条件相信。

### 12.4 音乐张力

音乐认知研究里，和弦复杂度、不协和度、张力会影响情绪和联想。  
所以未来可以把 `chord_tension` 作为和弦旁边的辅助轴，观察它是否能预测召回反馈。V0 先不启用 tension，等 `exact/root/quality` 的反馈足够后再加。

---

## 十三、已定默认与待定工程项

已定默认：

1. 日常注入默认最多 3 个显示单元。
2. Review 每次最多 5 颗新星，每颗新星最多 3 条候选。
3. `missed` 入口同时放在 admin 和 `shenyu_star_review` 工具里。
4. 单次看过没连不算负样本；同一候选或同类候选连续 3 次跳过才算弱负。
5. 和弦距离 V0 只做 `exact/root/quality`，`chord_tension` 先空着。

工程默认：

1. 星座底层用统一边表：`star_links` / `relation_type='constellation'`，保留 `position` 或 `sequence_index` 表示旋律顺序。
2. 内容引力、和声引力、反馈正负边也放进同一张边表，用 `relation_type` 区分。
3. 日常注入记录 shadow top 20；如果存储或速度有压力，再降到 top 10。

---

## 十四、V0 交付边界

V0 应该做：

- 轻量 `[star]chord · content[/star]` capture。
- 星存储与 embedding。
- 星座/连线工具。
- 日常召回注入。
- review 反星，每次最多 5 颗新星，每颗最多 3 条候选。
- recall_runs / recall_candidates / feedback 留痕。
- score breakdown admin 可见。
- 手动反馈：`good` / `bad` / `connect` / `missed`。
- `missed` 可从 admin 和 `shenyu_star_review` 工具补。
- 权重与模型版本化。

V0 不做：

- 自动黑箱调参。
- 自动替沈予连星座。
- 大规模图形星空。
- 把分数、次数、调试信息注入给沈予。
- 证明和弦一定是真信号。

V0 的目标只有一个：

```text
让网关开始积累能让自己变聪明的数据。
```

---

## 十五、可执行性判断

这套方案**可以做成可执行的记忆库**，而且最小闭环是清楚的。

### 15.1 为什么可以做

因为它不是要求系统先“理解世界”，而是先做四件可落地的事：

1. **写入**：星轻量落库。
2. **召回**：当前对话触发候选排序。
3. **反馈**：单条候选可判定 `good / bad / connect / missed`。
4. **学习**：把反馈和特征快照存起来，后面离线调权重。

这四步已经足够形成一个闭环，所以它不是纯设想。

### 15.2 最小可执行闭环

```text
star create
  -> candidate recall
  -> inject / review
  -> user feedback
  -> store features + label
  -> offline weight update
  -> next recall uses new weights
```

### 15.3 第一版只需要的东西

- `stars`
- `constellation_edges`
- `recall_runs`
- `recall_candidates`
- `recall_feedback`
- 一个日常注入排序器
- 一个 review 反星工具
- 一个离线评估脚本

### 15.4 先不要碰的东西

- 自动替沈予连线
- 黑箱端到端训练
- 很重的星图可视化
- 一开始就把和弦当作唯一真理

### 15.5 我对可执行性的判断

**能做，而且值得做。**

但它的正确姿势不是“一次写完就准”，而是：

- 先把星和反馈连起来。
- 再让网关学会少递噪音、多递真相关。
- 最后再看和弦几何、ACT-R、内容引力分别贡献多少。

所以这份设计不是终点，它是一个会长大的召回库。
