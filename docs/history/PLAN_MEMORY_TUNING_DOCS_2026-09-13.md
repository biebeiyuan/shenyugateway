# 记忆调参文档化 —— 边界说明（2026-09-13）

本文是动手前给圆圆看的边界稿，不是设计正本。批准后照它施工，完成后本文归档留痕；
产生的长期事实进 `DESIGN.md` / `docs/architecture/MEMORY_ROOM.md`，不留在这里。

## 起因

对比 Latent-memory 时，我读代码读得出"它做什么"，但读不出"它为什么"，于是自己编了两次动机、编错两次：
把 `_mem_date_note` 的相对天数当成指纹污染（其实是沈予给未来自己的闹钟），
把 Mem lane 的低粘性当成 bug（其实是"宁可丢缓存也不能漏该想起的"）。
两次都是代码正确、推断错误。地图把我送到了对的文件，所以这不是地图的缺口，
是**用意没有住所**。

同一轮里还撞见 `DESIGN.md` 的一句旧话骗过我一次，之后我就不太信文档、直接扎代码——
这个信任损失比那句错话本身贵。

## 不做什么（先说清楚）

- **不新建 `docs/architecture/MEMORY.md` 之类的总览文档。** 一本总览会变成知识的第二个家，
  然后像那句旧话一样静默过期，下一个 agent 花的钱不减，只是变成"读了还得验"。
  记忆子系统的正本已经有了：`DESIGN.md`（原则与改动边界）+ `MEMORY_ROOM.md`（Mem/Stars/Room 参考）。
- **不改任何检索、打分、注入行为。** 本轮是文档 + 注释 + 一处死代码清理，用户可见行为为零。
- **不动那五个 mem 语义阈值、不动 `star_min_score` 的活值 0.008、不换 embedding 模型。**
  换模型的判断依赖离线评测集，评测集还不存在（见第四件）。
- **不给 2/3 重叠门加 config 开关。** 它是缓存断点的粘性系数，不是手感旋钮；
  真要调得先有评测。本轮只把它写进阈值表并注明"写死在函数默认参数，无 Admin 项，故意的"。

## 要做什么

### 一、用意写进 docstring（最便宜，收益最大）

就在代码旁边补"为什么"，不是补"做什么"。本轮只补这次真的绊倒我的两处：

| 位置 | 补一句什么 |
|------|-----------|
| `memory_island.py::_mem_date_note` | 相对天数是闹钟语义，跨天桶时指纹随之改变是**预期的**；代价是那天 Mem lane 重排一次、丢一次缓存断点。`entering` 按 item id 算而非按指纹算，所以副作用（`mark_triggered` / 打戳）不会被重打。 |
| `memory_island.py::_legacy_forced_new_item` | mem 分支为什么破门：`entity` 是 `search_notes_contextual` 的 Layer 1 精确命中路，`promise` 是承诺。宁可丢缓存也不能漏该想起的——Mem lane 的低粘性是取舍结果，不是遗漏。 |

### 二、`docs/architecture/MEMORY_TUNING.md` —— 阈值与标度表（唯一新增文档）

它值得单独成文，因为它是**注释做得最差、表格做得最好**的形状：这些数字散在七个文件里，
只有摊在一张表上才能互相比较、才能看出"哪几个共用一套标度"。

每行四列：

- **住在哪** — `file::symbol` 形式，`tests/test_project_map.py::test_live_docs_symbol_anchors_still_resolve` 会解析，符号改名即红灯。
- **什么标度** — 例：`RRF 融合后（≈1/(k+rank) 量级，单通道上限 1/61≈0.0164）` / `0..1 余弦相似度` / `0..1 加权和` / `小时`。
- **为什么是这个值** — 一句话。
- **按什么标定** — 没标过就明写 `未标定`，学 Latent 的 `hit_floor() -> None`：不许照抄别人的数，也不许把拍出来的数写成像标定过的。

收进来的（本轮范围，约 20 行）：

- Stars：`star_min_score` 0.008、`star_related_min_score` 0.22、六个 `star_rrf_ch_*` 通道权重、`star_rrf_k` 60、`star_rrf_actr_floor` / `constant_boost` / `date_boost_max`、`star_recent_fatigue_penalty` 0.14、`star_scene_embedding_threshold` 0.45
- Mem：`mem_note_min_score` 0.45、四个语义/关键词阈值（0.25 / 0.40 / 0.50 / 0.30 / 0.42）、两个 cooldown
- Recall：`recall_vector_min_score` 0.42、`_ranking.py` 里两组线性权重（有向量 0.40/0.35/0.12/0.08/0.05，无向量 0.58/0.22/0.10/0.10）、`tier * 2.0`、graph `+0.72 / +0.24`
- Island：2/3 重叠门、`STAR_SOFT_DIRECT_COOLDOWN_TURNS` 8
- Embedding：`embedding_dim` 1024，附一句"以下阈值按 bge-m3 的余弦标度调出，换 embedder 会静默作废它们而 check 全绿"，点名是哪几个

**这张表要写清一件事**：`0.008` 和 `0.22` 不在同一套标度上——前者是 RRF 融合后，后者是 related 预筛的 0..1 加权和。
现在没有任何地方记着这件事，于是 `_crud.py:58` 的 `0.18`（RRF 之前那套标度的遗物）看起来像"另一个合理的 min_score"。

登记：`DOCS_MAP.md` § 现行文档 加一行；§ 内容归属 加一行说明"阈值的标度与标定出处"归它，别的文档只放指针。

### 三、修三处分叉的默认值 + 那句旧文档

我扫了全仓 44 处 `getattr(cfg, "字段", 兜底)`，其中 3 处兜底值与 config 默认值不一致：

| 位置 | 字段 | 兜底 | config 默认 |
|------|------|------|-------------|
| `stars/_crud.py::_min_score` | `star_min_score` | 0.18 | 0.008 |
| `mem_notes/_search.py` `_default_cooldown_hours` | `mem_note_default_cooldown_hours` | 72 | 12 |
| `context_builder.py` calendar offset | `calendar_context_day_offset` | 0 | 2 |

三处都不可达（字段在 `config.py` 里都有值），线上行为没有受影响——但它们都在骗顺着代码读的人。
病不在数值，在于**一个默认值有两个住所**，和"禁令没有第二个住所"是同一件事。

改法照 mem 已经用对的写法：兜底引用常量，不写字面量。
`_search.py:647` 的 `getattr(self.cfg, "mem_note_semantic_min_score", CONTEXT_SEMANTIC_MIN_SCORE)`
是仓里现成的正确形状——常量改了两边一起动，不会分叉。
`star_min_score` 没有对应常量，就直接删掉第三个参数（字段必然存在，`_cfg_float` 的 default 到不了）。

同一次改掉 `MEMORY_ROOM.md` § Mem Note Layer 那句——它写"归档/暂停的便签不由 2/3 门保留"，
这句是对的；缺的是"新进的 entity / promise 命中会主动破门"，读者会以为 Mem lane 和 Star lane 一样粘。

### 四、`DOCS_MAP.md` § 新线程入口 加一小节"按问题找"

地图现在按模块组织，而我这次的问题全是跨模块的：
"记忆一共有几条召回路、各自入口和判据在哪"、"一个阈值属于哪套标度"、"岛为什么这轮换了"。
四五行指路即可，不搬内容。

## 验证

- `python -m pytest -q tests/test_project_map.py`（新表的 `file::symbol` 锚点必须全部解析）
- `python -m pytest -q tests/test_star_memory.py tests/test_mem_notes.py tests/test_island_bumps.py`（删兜底值不改行为）
- `python scripts/check_audit_freshness.py`（黄灯不作为阻断，只看有没有新增提醒）
- `python scripts/resident_home.py check`；本轮预期是无住户影响（文档 + 注释 + 不可达兜底），
  按 AGENTS.md 用 `--no-impact` 或 `ack-shared` 明确记录，不含糊过去。
- **反向验证护栏真会红**：临时把表里一个 `file::symbol` 改成不存在的符号，确认 `tests/test_project_map.py` 失败，再改回来。
  照"加护栏前先量噪声"——没红过的护栏不算护栏。

## 不在本轮、留给下一轮

按性价比排，都要单独的边界说明：

1. `BAAI/bge-reranker-v2-m3` 作为二段拒绝门 + 建 HNSW 索引（两个 migration 里现在都是注释状态，今天走精确全表扫描）
2. 离线评测集（Latent 有七个测量脚本，我们零个）——第 4 项和换 embedder 的判断都压在它上面
3. Latent 的 `already_covered` 覆盖账本、冲突句式整轮弃权
4. 换不换 embedding 模型：实测在"每次离题放行 ≤3 块"这个工作点上 bge-m3 胜 Qwen3-0.6B/8B，
   ROC 交叉点在 3–5 块之间；在有第 2 项之前换模型是赌，不是优化
