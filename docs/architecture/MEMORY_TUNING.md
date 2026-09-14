# 记忆调参：阈值、标度与标定出处

本文回答一个问题：**一个数字属于哪套标度、按什么标定的。** 记忆系统的这些数散在七个
文件里，单看每一处都像"一个合理的分数线"，摊在一张表上才看得出它们并不在同一把尺子上。

不在本文范围：这些机制**做什么**（`DESIGN.md`）、Mem/Stars/Room 的现行行为
（`docs/architecture/MEMORY_ROOM.md`）、缓存断点与窗口（`REQUEST_CONTEXT.md`）。
本文只管尺子。

## 怎么读这张表

- **住在哪** 用 `file::symbol` 形式。`tests/test_project_map.py` 的
  `test_live_docs_symbol_anchors_still_resolve` 会解析每一个锚点，符号改名或消失就红灯。
- **标定出处** 写 `未标定` 不是缺陷登记，是诚实：它表示这个值是拍出来的、跑通了、没量过。
  **不许把拍出来的数写成像量过的**，也不许照抄别处的数——不同标度之间的数字互相没有意义。
- 一个 `config.py` 字段的默认值只有一个住所。代码里 `getattr(cfg, "字段", 兜底)` 的兜底
  必须与之逐字一致，由 `tests/test_config_default_homes.py` 看守（生产读不到那个兜底，
  但测试里的假 cfg 读得到，所以分叉会带着绿测试活下来）。

## 有几套标度

| 标度 | 量级 | 谁在用 |
|------|------|--------|
| **RRF 融合后** | 单通道上限 `1/(k+0+1)`，k=60 时 ≈0.0164；六通道加权和的实际落点在千分位 | Stars 最终注入线 |
| **0..1 加权和** | 各分量按权重相加后 clamp 到 1.0 | Stars related 预筛、Recall `_score_row`、Mem 便签打分 |
| **0..1 余弦相似度** | `1 - (a <=> b)`，pgvector 算出来的原始距离转相似度 | 所有向量门槛 |
| **乘法修正** | 1.0 是"不修正"，>1 放大、<1 压制 | Stars 的六个 modifier；便签只有热度这一个（且乘在 clamp 之内） |
| **计数 / 小时 / 天** | 物理单位 | cooldown、fatigue 窗口、日期偏移 |

**最容易踩的一脚**：`star_min_score`（0.008）和 `star_related_min_score`（0.22）
看着像同一种"最低分"，其实前者量在 RRF 融合之后、后者量在 related 预筛的 0..1 加权和上，
差两个数量级是**对的**。`stars/_crud.py` 里曾留着一个 `0.18` 的兜底值——它是 RRF 改造
之前那套标度的遗物，在写下来那天是对的，脚下的尺子换了它没跟着走。

## Stars

| 值 | 住在哪 | 标度 | 为什么是这个值 | 标定出处 |
|----|--------|------|----------------|----------|
| `star_min_score` 0.008 | `stars/_crud.py::_min_score` | RRF 融合后 | 注入总线。落在千分位是标度的自然结果，不是"几乎不设限" | 未标定 |
| `star_related_min_score` 0.22 | `stars/_crud.py::_related_min_score` | 0..1 加权和 | related 预筛，挡掉完全无关的候选再进 RRF | 未标定 |
| 六通道权重 1.0 / 0.8 / 0.6 / 0.7 / 0.4 / 0.5 | `config.py::RuntimeConfig`（`star_rrf_ch_*`） | RRF 通道系数 | content 最重，scene 最轻；顺序反映"哪条通道单独出现时更可信" | 未标定 |
| `star_rrf_k` 60 | `config.py::RuntimeConfig` | RRF 常数 | RRF 论文默认值。k=60 时 rank0 与 rank99 的比值只有 2.62，**名次几乎不携带信息**，实际退化成"命中了几条通道"的加权计数 | 沿用论文默认，未在本仓语料上量过 |
| `star_rrf_actr_floor` 0.5 | `config.py::RuntimeConfig` | 乘法修正下界 | 再暗的星也只压到一半，不让 ACT-R 亮度单独把一颗星判死 | 未标定 |
| `star_rrf_constant_boost` 1.3 | `config.py::RuntimeConfig` | 乘法修正 | 常驻星的固定放大 | 未标定 |
| `star_rrf_date_boost_max` 0.3 | `config.py::RuntimeConfig` | 乘法修正上限 | 纪念日最多放大 30% | 未标定 |
| `star_recent_fatigue_penalty` 0.14 | `stars/_crud.py::_recent_fatigue_penalty` | 乘法修正扣减 | 刚注入过的星压 14%。**普通聊天故意关掉这条**，岛的稳定性交给 2/3 重叠门，不靠人为轮换 | 未标定 |
| `star_recent_fatigue_hours` 6 | `config.py::RuntimeConfig` | 小时 | 上面那条扣减的时间窗 | 未标定 |
| `star_scene_embedding_threshold` 0.45 | `stars/_scene.py::_classify_scene_by_embedding` | 0..1 余弦 | 场景标签的向量归类线。0.45 同时是函数默认参数、`_load_scene_config` 的两处兜底和 config 默认，四处一致 | **按 bge-m3 的余弦标度调出** |
| base_score 权重 0.55 / 0.25 / 0.20 | `stars/_recall.py::_score_rows` | 0..1 加权和 | content / keyword / chord 三分量。`content_score = max(内容词重叠, 向量分)` | 未标定 |
| `star_rrf_activation_weight` 0.15 | `config.py::RuntimeConfig` | 乘法修正的权重 | 热度修正 `1 + w·ln(1+活性)` 里的 w。取 0.15 是让日常活性（一天进一次岛的稳态 ≈0.55）落在 +6% 上，连着一周（≈2）落在 +16% 上 | 按下面那条实测的名次预算反推，未在真实语料上量过 |

六个 modifier 的乘法链在 `stars/_recall.py::_score_rows`：
`final = rrf_score * actr_mod * novelty_mod * constant_mod * fatigue_mod * date_mod * activation_mod`。
`ignored_penalty` 被算出来也写进了日志，但**不在这条链里**——它目前只是可观测量，不参与排序。

### 谁在拉同一个信号（未解决，2026-09-14 记录）

上面那张表逐行读得出「每个阈值住哪、什么标度」，读不出**哪几个量在同时拉同一颗星**。
这一节补的就是那件事，因为 `activation_mod` 恰好是从这个缺口漏进去的：加它的时候
`actr_floor` 和新权重在表里各占一行，都写着"未标定"，看不出它们指向同一个信号。

`actr_mod`、`novelty_mod`、`activation_mod` 三个都由「这颗星进了 Memory Island」驱动，
方向是**加、减、加**，实测三者乘积随想起次数从 0.500 涨到 0.688 之后一路跌回 0.509
——越常被想起越沉。完整的实测表、为什么不在同一次改动里修掉、以及动它之前要先回答
哪个问题，都在 `MEMORY_ROOM.md` § 同一个动作驱动三个乘数，不在这里重复一遍。

调这三个值里的任何一个之前先读那一节：单独调一个的效果会被另两个吃掉一部分。

### 热度（activation）

活性不是一个存下来的分数，是读时从事件账本算的：`shenyu_heat_events` 一条记忆一轮一行，
`shenyu_star_activation` / `shenyu_mem_note_activation` 两个视图按 `sum(0.82^age_days)`
在 90 天窗口内求和。0.82/天的半衰期是 3.5 天，90 天外的权重是 3e-9，所以窗口不是近似而是
数值上的等价。**没有夜间衰减任务**，因此"漏跑一晚"这件事不存在。

| 值 | 住在哪 | 标度 | 为什么是这个值 | 标定出处 |
|----|--------|------|----------------|----------|
| 保留率 0.82/天 | `20260914_memory_heat_ledger.sql`（两个视图的 `power(0.82, …)`） | 衰减率 | 半衰期 3.5 天。比 ACT-R 常用的 `t^-0.5` 忘得快，因为这里量的是"最近还在想着吗"，不是长期记忆强度。差多少：单次想起过 14 天，`t^-0.5` 还剩 0.27，这里只剩 0.06；过 100 天前者仍剩 0.10，这里已经是 0 | 未标定 |
| 90 天窗口 | 同上（`interval '90 days'`） | 天 | 0.82^90 ≈ 3e-9，落在双精度噪声里；窗口只是让视图不用扫全表 | 按上面那条保留率算出来的 |
| `ACTIVATION_MOD_MAX` 1.3 | `memory_heat.py::ACTIVATION_MOD_MAX` | 乘法修正上限 | 和 `star_rrf_constant_boost` 同一个量级，刻意的：热度最多和"恒星"一样重，不该更重 | 取自恒星加成，未独立标定 |
| `MEM_NOTE_ACTIVATION_WEIGHT` 0.15 | `mem_notes/_search.py::MEM_NOTE_ACTIVATION_WEIGHT` | 乘法修正的权重 | 和星星那边同一个默认值，但**走各自的住所**：便签的分数要跟 `mem_note_min_score` 这几条固定线比大小，星星那边只排序，将来大概要分开标定 | 抄自星星侧的默认值 |

**为什么要取对数再封顶。** 视图给的活性没有上界：每天进岛 n 次的稳态是
`0.82·n/(1-0.82) = 0.547n`，n=20 就到 11。线性乘 `1+0.15·11` 是 2.6 倍，两件事同时坏——
便签的分数会顶出 0..1 值域，让 `mem_note_min_score` 那几条线静默漂移；而且没有上界的
使用权重恰好压掉沈予要的那个东西（"偶尔冒出一个我没料到的"），因为常想起的更容易再被
想起，进过的更容易留下、留下的又加热。那是车辙不是地形。所以照 ACT-R 本来的样子取对数
（`B = ln Σ t^-d`），再 clamp 到 1.3。

**1.3 倍值多少个名次。** k=60 的 RRF 里相邻名次只差 1.6%，所以"封顶就翻不动语义命中"
是句假话。2026-09-14 在 `tests/test_memory_activation.py` 的假 Supabase 上实测：满热度
（modifier 顶到 1.3）能把一颗星从第 19 名提到第 1 名，第 20 名提到第 3 名，第 26 名只能
到第 7 名。默认权重 0.15 下：活性 0.55 值 4 个名次，活性 2 值 10 个，顶格 11 值 18 个。
这是本仓少数量过的数之一，量的是**假语料上的名次预算**，不是真实召回质量。

两条线的热度都只由「新进动态岛」写（`context_builder.py`），沈予手动 `search_stars` /
`recall` 想起来的**不记热度**——这跟他自己说的"被想起来"是反的，是当前的取舍不是设计：
`shenyu_heat_events.event_type` 的 check 里留好了 `manual_search` / `tool_use`，
真要记的话手动召回应该**权重更高**而不是更低。

## Mem 便签

| 值 | 住在哪 | 标度 | 为什么是这个值 | 标定出处 |
|----|--------|------|----------------|----------|
| `mem_note_min_score` 0.45 | `mem_notes/_search.py::search_notes` | 0..1 加权和 | 显式搜索（不是自动召回）的分数线 | 未标定 |
| `CONTEXT_KEYWORD_MIN_SCORE` 0.25 | `mem_notes_relevance.py::CONTEXT_KEYWORD_MIN_SCORE` | 0..1 加权和 | 第二层关键词召回线，比显式搜索松：这一层已经被特异性过滤挡过一道 | 未标定 |
| `CONTEXT_SEMANTIC_MIN_SCORE` 0.40 | `mem_notes_relevance.py::CONTEXT_SEMANTIC_MIN_SCORE` | 0..1 加权和 | 无锚点支撑时的语义线 | 未标定 |
| `CONTEXT_SEMANTIC_MIN_VECTOR_SCORE` 0.50 | `mem_notes_relevance.py::CONTEXT_SEMANTIC_MIN_VECTOR_SCORE` | 0..1 余弦 | 同上，向量分单独还要过这条 | **按 bge-m3 的余弦标度调出** |
| `CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE` 0.30 | `mem_notes_relevance.py::CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE` | 0..1 加权和 | 有锚点相关词时可以放松 | 未标定 |
| `CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE` 0.42 | `mem_notes_relevance.py::CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE` | 0..1 余弦 | 同上的向量线 | **按 bge-m3 的余弦标度调出** |
| 打分权重 0.50 / 0.30 / 0.10 / 0.02 / 0.03 | `mem_notes/_search.py::_score` | 0..1 加权和 | trigger / content / anchor / type / recency；`never_seen_bonus` 另加 0.05 | 未标定 |
| 热度修正 | `mem_notes/_search.py::_score` | 乘法修正，**乘在 `min(1.0, …)` 之内** | 见 Stars 的〈热度〉小节。位置是硬约束：乘在 clamp 外面，分数就能顶到 1.3，上面这三条固定线一起静默漂移 | 见〈热度〉 |
| `mem_note_limit` 3 | `config.py::RuntimeConfig` | 计数 | **两条水源共用的总量**（日期提醒 + 上下文召回），提醒优先占位。动态岛是缓存断点锚，通道没有上限等于可缓存前缀没有上限 | 按缓存成本定，非检索质量 |
| `mem_note_soft_cooldown_hours` 12 | `mem_notes/_search.py::_context_cooldown_hours` | 小时 | 自动召回的软冷却 | 未标定 |
| `mem_note_default_cooldown_hours` 12 | `mem_notes/_search.py::_default_cooldown_hours` | 小时 | **新建**便签的 `cooldown_hours` 初值 | 未标定 |
| 旧行 `cooldown_hours` 兜底 72 | `mem_notes/_search.py::_in_cooldown` | 小时 | 读旧行时的历史默认，**和上面那个 12 不是一回事**，不能一起改 | 历史值 |
| `mem_note_dedupe_turns` 6 | `mem_notes/_search.py::_context_dedupe_turns` | 轮次 | 同 session 内连续重复的抑制窗 | 未标定 |

`mem_notes/_search.py::_anchor_overlap` 返回
`min(1.0, len(hits)/max(1,len(all_anchors)) + 0.3)`——那个 `+0.3` 是地板，
会把"1/3 锚点命中"抬到 0.63，和"全中"的 1.0 之间只差 0.37。命中率本身的分辨力被压掉了大半。

## Recall 统一索引

| 值 | 住在哪 | 标度 | 为什么是这个值 | 标定出处 |
|----|--------|------|----------------|----------|
| `recall_vector_min_score` 0.42 | `config.py::RuntimeConfig` | 0..1 余弦 | 向量召回的入场线 | **按 bge-m3 的余弦标度拍的，未标定** |
| 有向量权重 0.40 / 0.35 / 0.12 / 0.08 / 0.05 | `recall/_ranking.py::_score_row` | 0..1 加权和 | keyword / vector / field / importance / recency | 未标定 |
| 无向量权重 0.58 / 0.22 / 0.10 / 0.10 | `recall/_ranking.py::_score_row` | 0..1 加权和 | 没有向量分时重新分配，keyword 吃掉大头 | 未标定 |
| graph 加分 +0.72 / +0.24 | `recall/_ranking.py::_score_row` | 直接加在 0..1 分上 | direct（确认别名精确命中）/ related（一跳）。0.72 大于任何单一权重，**等于把图谱命中放在其他信号之上** | 未标定 |
| `tier * 2.0` | `recall/_query.py::recall`（`scored.append`） | 排序前缀 | 匹配档位。步长 2.0 远大于分数值域，所以**档位之间是硬性偏序**，权重怎么调都跨不过去 | 刻意如此 |
| `phrase_bonus` 0.18 | `recall/_ranking.py::_score_row` | 0..1 加权和 | 整个 query 原样出现在正文里 | 未标定 |
| 无 token 时 `token_score` 0.15 | `recall/_ranking.py::_score_row` | 0..1 加权和 | query 分不出词时给的底分 | 未标定 |
| `recall_candidate_limit` 160 | `config.py::RuntimeConfig` | 计数 | 候选上限（成本天花板，不是质量判据） | 按成本定 |

`recall/_ranking.py::_score_row` 把命中词写成 `keyword:` 开头的 reason 字符串，只取前 6 个
（`token_hits[:6]`）。这个截断是给人看的，但下游有判据在读这个字符串
（`mem_notes_relevance.py::_semantic_anchor_hits` 解析 `keyword:` 前缀），
所以**显示截断和语义判据是耦合的**：第 7 个命中词对那个判据不存在。

## 动态岛

| 值 | 住在哪 | 标度 | 为什么是这个值 | 标定出处 |
|----|--------|------|----------------|----------|
| 2/3 重叠门 | `memory_island.py::resolve_memory_island`（`overlap_threshold` 默认参数） | 比例 | 旧岛与新提案的 ID 重合率。**写死在函数默认参数里，没有 Admin 项也没有环境变量，这是故意的**：它是缓存断点的粘性系数，不是手感旋钮，要调得先有离线评测 | 未标定 |
| `STAR_SOFT_DIRECT_COOLDOWN_TURNS` 8 | `memory_island.py::STAR_SOFT_DIRECT_COOLDOWN_TURNS` | 真实用户轮次 | 软点名破门的冷却，Admin 可改。只有 `initial` / `new_user` / `branch` 计数 | 未标定 |
| `island_bump_limit` 8 | `config.py::RuntimeConfig` | 计数 | 小突起条数上限 | 未标定 |

两条 lane 的破门规则不对称，见 `memory_island.py::_legacy_forced_new_item`：Star 侧只认
排名器打的 `force_island_rewrite`（门很窄），Mem 侧认 `entity` 和 `promise`。`entity`
是便签召回的第一层精确锚点命中，所以 **Mem lane 的实际粘性远低于 Star lane**——
这是"宁可丢一次缓存断点，也不能让该想起来的没想起来"的取舍结果，不是遗漏。

`memory_island.py::_mem_date_note` 把相对天数写进渲染文本，所以带 `remind_on` 的便签
跨天时指纹会变、Mem lane 重排一次。这也是要的：那句话是沈予给未来自己的闹钟。
代价封在一天一次的缓存断点上，不牵动便签簿记（`entering` 按 item id 算，不按指纹算）。

## Embedding

当前模型 `bge-m3`，`embedding_dim` 1024（`config.py::RuntimeConfig`）。
维度写在四处 SQL 声明里：`20260526_shenyu_recall_index.sql`、
`20260527_shenyu_recall_vector_rpc.sql`、`20260618_shenyu_stars.sql`（两处）。

**换 embedding 模型会静默作废上表中标着"按 bge-m3 的余弦标度"的四个阈值**，
因为余弦分布是模型自己的性质，不是通用刻度。重算全库 embedding 只要几分钱，
`check` 也会全绿——**绿灯不代表这四条线还在原来的位置上**。所以换模型之前得先有
离线评测集，否则是赌不是优化。

两处向量索引（HNSW）在 `20260526_shenyu_recall_index.sql` 和 `20260618_shenyu_stars.sql`
里目前都是注释状态，也就是说 `order by embedding <=> q` 走的是精确全表扫描 + 全排序。
现在库小看不出来，它只会变慢不会报错。

## 现在没有的东西

**离线评测集**。`tests/` 和 `scripts/` 里没有 golden set、没有 ndcg/mrr/precision 计算、
没有阈值标定脚本。所以上表里绝大多数"未标定"是真的没量过，不是懒得写来源。
这直接决定了两件事的顺序：**先有评测，再谈调参和换模型**。
