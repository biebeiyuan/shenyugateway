# Shenyu Gateway — 优化执行方案

> 来源：2026-07-01 的一次多视角代码审查（6 个视角扫描 + 对抗式复核）。
> 共 17 条存活发现，其中 **#1 删死代码** 和 **#2 fire-and-forget 任务引用** 已在 commit `4562feb` 完成。
> 本文档是剩余 15 条的可执行清单，按"先低风险高收益、后大重构"排序，供后续慢慢做。
>
> **总原则**（沿用 `docs/history/REFACTOR_PLAN_2026-07.md`）：
> - 以**函数名**为锚，不按行号机械搬（行号仅作提示，会随改动漂移）。
> - 每个 Phase 单独 commit，单独 review diff。
> - 重构中**不**顺手改业务逻辑、文案、fallback、阈值、上下文层顺序。
> - 改完跑 `python -m pytest`（基线：283 passed）。
>
> **重要背景**：本次审查**没有发现任何 high 严重度问题**。下列全是结构债、低概率并发风险（后果温和）、测试盲区。可以从容做，不是救火。

---

## 优先级总览

| Phase | 项 | 类型 | 收益 | 风险 | 工作量 |
|-------|-----|------|------|------|--------|
| A | 场景描述向量缓存 | 性能 | 高（热路径每轮省 6 次远程 embed） | 低 | 小 |
| B | context build 并行化 | 性能 | 中（每轮省 1-2 个 Supabase 往返） | 低 | 小 |
| C | 中文停用词去重统一（`它`） | 一致性 | 中（消除静默漂移） | 低 | 小 |
| D | 配置 fallback 对齐 + 小重复抽取 | 一致性/整洁 | 低（防未来踩坑） | 低 | 小 |
| E | 测试硬化（打分/注入核心逻辑） | 回归保险 | 中 | 无 | 中 |
| F | 拆 `gateway_tools.py`（mixin 包） | 结构 | 中 | 低（机械） | 中 |
| G | 并发竞态加固（心跳/归档去重） | 健壮性 | 低（低概率） | 中 | 中 |

> 建议顺序：**A → C → B → E → F → D → G**。A/C/B 收益直接且小，E 给后续重构兜底，F 是最大块的机械重构，D/G 可机会性穿插。

> **状态核对（2026-07-26，Claude）**：
>
> | Phase | 状态 | 证据 |
> |-------|------|------|
> | A 场景向量缓存 | ✅ 已完成 | `stars/_scene.py` 的 `_DESC_VECTOR_CACHE` |
> | B context build 并行化 | ✅ 已完成 | `context_builder.py` 合并 gather（AUDIT_MATRIX 区域五已确认） |
> | C 中文停用词统一 | ✅ 已完成 | `recall.py::is_generic_chinese_fragment` 为单一来源，`mem_notes_relevance.py` 复用 |
> | D 配置 fallback / 去重 | ◐ D4 已完成（2026-07-26） | D4：`_vector_literal` 收敛到 `embeddings.vector_literal`、`_json_dict` 收敛到 `utils.json_dict`，recall 与 stars 共享单一实现；D1 `stars/_crud.py` 死 fallback 仍未处理 |
> | E 测试硬化 | ✅ 已完成 | 硬化测试文件均已存在；全仓测试早已超过 283 基线（2026-07-26 为 550+） |
> | F 拆 gateway_tools.py | ✅ 已完成（2026-07-26） | `shenyu_gateway/gateway_tools/` mixin 包；拆前删除了 ask_memory / search_primary_texts / meta_summaries 死代码，并新增 broker 描述与 daily 名单守护测试 |
> | G 并发竞态加固 | ⬜ 未做 | `chat_archive.py` 仍是 insert_many；`store/_heartbeats.py` 无 claim |
> | REFACTOR 遗留：gateway.py 兼容 wrapper 清理 | ⬜ 未做 | 原 REFACTOR_PLAN Phase 4；前置的 import/monkeypatch 契约清单未整理（AUDIT_MATRIX 区域一 P3） |
> | REFACTOR 遗留：Mem0View.vue 拆分 | ⬜ 未做 | 原 REFACTOR_PLAN Phase 5；前端大文件，单独一轮处理 |
>
> 下文行数与行号均为 2026-07-01 快照；执行剩余项（D、G）时以函数名为锚重新核对。

---

## Phase A：场景描述向量缓存（性能，强烈建议先做）

**问题**：`stars/_scene.py::_classify_scene_by_embedding`（约 :63-88）在每次关键词未命中时，对 6 条**静态**场景描述逐条 `await embedding_client.embed(desc)`（:79），每条都是一次新建 httpx client 的远程往返、无缓存。`daily` 场景关键词为空，所以"未命中→走 embedding 兜底"是常见路径，且 `_classify_scene` 在 `stars/_recall.py` 的召回流程里、**每轮聊天都可能走到**。一次 miss = 7 个串行远程 embed（6 描述 + 1 query）。

**改法**（`stars/_scene.py`）：
1. 把 6 条描述向量缓存一次。描述是 config 驱动（`_load_scene_config` / `star_scene_rules_path`），所以缓存 key 用"描述文本"或 config 内容的 hash，避免配置热更新后用旧向量。
   - 实现选项：模块级 `dict[str, list[float]]`，key 为 `desc` 文本；命中直接用，未命中才 embed 并存。
2. （次要、可选）复用 query 向量：注意 `_classify_scene_by_embedding` 用 `query[:800]`，而 `_embedding.py::_vector_rows` 用 `query[:1600]` —— 截断长度不同，复用需要权衡，**不强求**。先做描述缓存就能拿回绝大部分延迟。

**验证**：
- [ ] 新增/补强 `tests/test_star_memory.py`：同一描述第二次分类不再触发对该描述的 embed（用 fake embedding client 计数调用次数）。
- [ ] `pytest tests/test_star_memory.py` 通过。

**边界**：不改场景规则、不改 threshold（0.45）、不改 `_cosine_similarity`。

---

## Phase B：context build 并行化（性能）

**问题**：`context_builder.py::build_context_package`（约 :145-209，非海信分支）里，日历 `await calendar_context_pages()`（:145）、矛盾书架 `await _conflict_shelf_books()`（:157）、然后 mem_notes+stars 的 `asyncio.gather`（:209）是**串行**的。三组 Supabase 读互不依赖，串行纯属浪费。底层是真异步 client（httpx），并行收益是真实的。

**改法**（仅 `build_context_package` 内部，localized）：
- 把日历、矛盾书架（当 `not is_hisense and inject_conflict_shelf`）、mem_notes、stars 这几个独立协程合进**一个** `asyncio.gather`，之后再把结果写回 `package`。
- 海信分支保持独立，不动。
- **保持 fail-soft 语义**：日历内部 `load` 和 `_conflict_shelf_books` 都已 try/except→[]；mem/star 的 gather 是 bare gather（会传播异常）——合并后让 mem/star 仍是唯一可能 raise 的，与今天一致。

**注意**：合并后 `trace_log` 的分阶段计时（`calendar_start/done`、`conflict_shelf_start/done`、`memory_tasks_start/done`）会失去粒度。取舍：要么保留一个合并的 start/done 标记，要么接受更粗的 tracing。

**验证**：
- [ ] `pytest tests/test_gateway_hisense_context.py tests/test_calendar.py` 通过。
- [ ] 手测一轮非海信请求，确认上下文内容与改前一致（顺序/内容不变，只是更快）。

---

## Phase C：中文停用词去重统一（一致性，含一处真实漂移）

**问题**：通用中文前后缀停用词逻辑被内联在多处，且**已经漂移**：
- `mem_notes_relevance.py::_generic_chinese_semantic_fragment`（:419-428）的 `generic_prefixes` **包含** `它`（:424）。
- `recall.py`（约 :170，`recall_terms` 附近的前缀元组）**不含** `它`。

后果（已用 `它的事` 实跑验证）：同一个 3-4 字、`它`开头的自动关键词，在 recall 路径被当作有效索引词，在便签锚点路径却被当通用词丢弃——非对称、难调试。爆炸半径窄（只影响"它"开头的 3-4 字自动关键词），但是真实的静默漂移，且这类逻辑散落 3 处，未来还会继续漂。

**改法**：
1. 把"前缀/后缀元组 + `is_generic_chinese_fragment(text)` 谓词"抽成**单一来源**。建议放在 `recall.py`（紧挨 `recall_terms`）或 `utils.py`。
2. 让 `_generic_chinese_semantic_fragment` 和 recall 侧调用同一个谓词。
3. **刻意**统一 `它`：它是常见代词，作为通用词处理大概率是对的 → 让 recall 侧也包含 `它`（即向 mem_notes 侧看齐）。在 commit message 里写明这是有意决策。
4. **不要**整函数合并：`recall.py` 的 `_mem_note_keyword_anchor_is_specific`（:156）和 `mem_notes_relevance.py::_keyword_anchor_is_specific`（:693）在 `len<=2` 的白名单分支不同（硬编码集合 vs seed 逻辑），只共享"前后缀通用片段"这一块，别动白名单。

**验证**：
- [ ] 加测试：`它的事` 在两条路径行为一致（都判为 generic）。
- [ ] `pytest tests/test_recall.py tests/test_mem_notes.py` 通过。

---

## Phase D：配置 fallback 对齐 + 小重复抽取（一致性/整洁，可机会性做）

都是"无 bug、纯防未来踩坑"的小清理，单独成一个 hygiene commit 即可。

**D1. `star_min_score` 死 fallback 对齐**：`stars/_crud.py::_min_score` 调 `_cfg_float(self.cfg, "star_min_score", 0.18)`，但 config 默认是 `0.008`（差 22 倍）。`config.py` 的 env helper 已带 0.008，所以现实中走不到 0.18——是误导性死字面量。把 `0.18` 改成 `0.008` 与单一来源对齐（同文件的 `_related_min_score`=0.22、`_recent_fatigue_penalty`=0.14 都已正确镜像，只有它是异类）。一字符级改动。

**D2. mem_note cooldown fallback 统一**：`create_note` 走 `_default_cooldown_hours()`→12，但 `_prepare_note_update`（`mem_notes/_crud.py:463`）和 `mem_notes/_search.py:602,606` 硬编码 fallback `72`。只在 schema-invalid/缺 cfg 属性时触发（正常流程走不到），但应统一走 `_default_cooldown_hours()` 消除 stale `72`。定位为一致性 hygiene，不是 bug 修复。

**D3. `safe_int` 抽取**：`mem_notes/_validation.py::_int_range` 与 `stars/_helpers.py::_safe_int` 逐字节相同（4 参签名、同体）。抽一个 `safe_int(value, default, min, max)` 到 `utils.py`，两边委托。
   - **只做 `safe_int`**。`_clamp` / `_float_range` / `_safe_float` 那一族签名和 None/falsy 处理**确实不同**，合并有静默改变行为的风险，**别碰**（审查已确认这族不值得统一）。

**D4. `_vector_literal` / `_json_dict` 去重**：`recall.py:309-310` 与 `stars/_helpers.py:116-117` 的 `_vector_literal` 逐字节相同——这是 pgvector 序列化契约（`.9g` 精度），两个子系统写/查同一个 Supabase 向量列，若哪天一份精度漂了会静默不一致。把 `_vector_literal` 提到 `embeddings.py`（它已管 `expected_dim`）。`_json_dict` 提到 `utils.py`。
   - **注意**：`_json_dict` 是 total（永远返回 dict），与现有 `utils.coerce_json_object`（失败返回 None）**契约不同**，**不要**合并进 `coerce_json_object`。

**验证**：
- [ ] 每个子项改完 `pytest` 全绿。
- [ ] D1 改后确认 `star_min_score` 注入行为无变化（默认本就 0.008）。

---

## Phase E：测试硬化（回归保险，建议在 F 之前做）

这些是"选择性浮现"核心打分逻辑的回归盲区——一旦回归会**静默降低记忆质量**且现有测试抓不到。无 bug，纯保险。建议在大重构（F）之前补上，给重构兜底。`FakeSupabase` 框架已存在（见 `tests/test_star_memory.py`、`tests/test_conflict_and_archive.py`），多数测试成本低。

**E1. 星星 RRF 融合 + 5 乘法修正**（`stars/_recall.py::_score_rows`，约 :357-412）：
- 现状：无任何测试断言数值分数或 2+ 星的相对排序。乘法链若被误改成加法、或 rank 分母 off-by-one，无测试报警。
- 加法：构造 3-4 个落在不同通道 rank 的 row + 种 `activation_count` + `is_constant`，直接调 `_score_rows`（async，经 FakeSupabase），断言（a）竞争星的相对顺序，（b）某一行的近似 `final_score` 和 `rrf_contributions`。

**E2. 星图 harmony 双向/关系加成**（`stars/_activity.py::_harmony_scores`，约 :18-71）：
- 现状：零覆盖。直接决定"用户没提到的星被不被拉进来"（喂 `related_signal` 和 RRF 的 `ch_harmony` 0.7 通道）。
- 加法：种 `shenyu_star_links` 的单向 constellation 边 + 双向 harmony 边，断言：正向边总是计分；反向边仅在 bidirectional=true 时计分；constellation 得 1.0×、其他 0.75×；confidence×weight 过 clamp。

**E3. constellation_pull 邻居扩展**（`stars/_recall.py::_constellation_pull`，约 :192-250）：
- 现状：chat_injection 测试都不建连线，这条路径零覆盖。
- 加法：一颗强匹配星 constellation 连到一颗弱星，limit=2，断言邻居填满 slot 2；再把邻居标 explicitly_negative，断言被排除；额外断言"非双向的反向连线不被拉入"（最微妙的分支）。

**E4. 心跳归档 settle 窗口 + soft-delete**（`heartbeat_archive.py`，约 :33-97）：
- 现状：灾备代码，零覆盖，回归会静默到"真需要备份时才发现"。
- 加法：用 fake store + fake supabase，种跨 settle 窗口的心跳，断言只有 settled 的被 upsert 并标记 synced；删一条 synced 的 SQLite 行，断言 `_reconcile_deleted` 只对那个 archive id 设 `deleted_at`、不动其他；覆盖 >50 的分块路径。顺带 pin "空内容行被标 synced 但不归档"的行为。
  - `test_conflict_and_archive.py` 的 FakeSupabase 可复用，只需加一个 `upsert` 方法。

**E5.（可选，低优先）ACT-R 零/单次激活边界 + fatigue 窗口边缘**（`stars/_activity.py`）：
- 用**宽松区间**断言（0 行→缺省、fresh→>0.8、1 年前→~0），记录负 log 路径这个"未来编辑者想不到的脚印"，但别 pin 死浮点（那会和"tuning 常量本就会变"的设计打架）。
- **不要**断言任何 silence/no-action 惩罚——那个克制是有意的。

**验证**：
- [ ] 每条新增测试先确认"改坏对应逻辑时会失败"（红→绿），否则等于没测。
- [ ] `pytest` 全绿。

---

## Phase F：拆 `gateway_tools.py`（结构，最大一块，机械重构）

**问题**：`gateway_tools.py`（1412 行，现已是最大源文件）里 `GatewayToolService`（:206 起）混了 ~40 个 1-3 行薄委托方法 + 两个自包含子系统。`docs/history/REFACTOR_PLAN_2026-07.md` 本就定了 ≤800 行目标。

**两个可抽出的内聚子系统**（均经 grep 确认边界）：
1. **Supabase 过滤 DSL**：`_build_supabase_filter_params`(:1299)、`_build_supabase_operator_params`(:1309)、`_normalize_operator_shape`(:1321)、`_parse_operator_condition`(:1329)、`_looks_like_operator_map`(:1347) —— 纯字符串解析，**无外部调用方**，只被本类的 supabase_query/insert/update/delete 用。
2. **主文本排序引擎**：`_collect_primary_text_candidates`(:1129)、`_row_to_chunks`(:1189)、`_score_passage`(:1223)、`_why_passage`(:1230)、`_base_salience_for_source`(:1247)、`_body_bonus_for_item`(:1262)、`_recency_score`(:1274) + 模块常量 `_split_paragraph_chunks`/`_keyword_overlap_score`(:51/:98) —— 纯打分。公开入口 `surface_passages`(:740)、`search_primary_texts`(:767) 经 tool_registry handler 和 `calendar_service.py` 到达。

**改法**（mixin 包，同 `stars/`、`mem_notes/`）：
```
gateway_tools/
  __init__.py        ← 组装 GatewayToolService(从 mixin)，re-export GatewayToolService + configure_gateway_tools
  _supabase_dsl.py   ← SupabaseDslMixin（上面第 1 组，全 internal）
  _primary_text.py   ← PrimaryTextMixin（上面第 2 组 + 两个模块常量）
  （其余薄委托 + GatewayToolRuntime 留在 __init__.py 或 _service.py）
```
- 7 个调用方全走 `from .gateway_tools import GatewayToolService`（+ tool_registry 的一个 `_runtime` import）。包级 re-export 后**零影响**。
- 这是纯机械搬运，落地后 facade ~550-600 行。
- **如果嫌全拆重**：只抽这两个子系统进 mixin、其余不动，单这一步就把主文件降到 ~550-600 行。

**验证**（沿用 `docs/history/REFACTOR_PLAN_2026-07.md` 的 checklist）：
- [ ] `python -c "from gateway import app"` 不报错。
- [ ] `git diff` 除 import/函数位置/mixin 组装外，无业务逻辑变化。
- [ ] 无 `from module import *`，无新 import cycle。
- [ ] `pytest` 全绿（283）。
- [ ] 7 个调用方（tool_registry、calendar_service 等）import 不变。

---

## Phase G：并发竞态加固（健壮性，低概率，可最后做）

单 worker 单事件循环下这些都是低概率、后果温和的问题。不紧急，但 claim-on-read 模式能顺带带来崩溃安全性。

**G1. 心跳 read-then-mark 非原子**（`context_builder.py` 读 + `private_capture.py` 标记 + `store/_heartbeats.py`）：
- 真实窗口是"读到标记之间"跨越了整个 LLM 回复。请求 A 读了 NULL 行还没标记，请求 B 进来又读到同一批 → 同一批心跳被注入两次（模型看到自己的私密心跳重复，非数据丢失）。
- 改法：read-and-claim 原子化——`get_pending_heartbeats` 同时盖一个短期 claim（`UPDATE ... SET injected_at=now WHERE id IN (SELECT ... LIMIT n) RETURNING *`，一个连接/事务内），一行只能交给一个请求。顺带崩溃安全。
- 海信路径（`context_builder.py` 海信分支）同理，如果那个池将来出现并发。

**G2. chat_archive 去重竞态**（`chat_archive.py::archive_window`，约 :152-184）：
- 同 session 两个近乎同时的轮次都通过 step1 的"未见"检查 → 都 POST → Supabase 出现重复 L0 行（归档浏览页显示重复）。注意这是**唯一**不带 upsert 的归档写入路径（heartbeat_archive、recall、stars/_crud 都 upsert）。
- 最省事修法：给 `(session_tag, content_hash)` 加 Supabase 唯一约束 + 把这一处 `insert_many` 换成 `upsert(on_conflict=...)`，顺便和其他三处归档路径一致。
- 替代：claim-before-insert（先 `INSERT OR IGNORE` 标 seen 取 rowcount，只插确认认领的）——但 `mark_archive_hashes_seen` 当前不返回 rowcount，需小改签名。
- **不建议**用 per-tag asyncio.Lock（给 fire-and-forget 设计加了它刻意避免的状态）。

**验证**：
- [ ] G1/G2 各加一个并发模拟测试（两个 overlapping 协程跑同一输入，断言只注入/归档一次）。
- [ ] `pytest` 全绿。

---

## 已完成（commit `4562feb`，仅作记录）

- **删死代码**：`tool_registry.py` 的 `_broker_tool_summary` + `_BROKER_TOOL_HINTS`（无调用方）。
- **修 fire-and-forget 任务引用**：`prepare_messages.py` 用 `_spawn_background_task` 保强引用 + 完成清理；`chat_archive.py` 加 `CancelledError` 分支。

---

## 收尾全量验证（任何 Phase 后都可跑）

```powershell
python -m py_compile shenyu_gateway\*.py shenyu_gateway\**\*.py
python -m pytest
python -c "from gateway import app"
```

基线：**283 passed**。任何 Phase 让数字下降都要先查清楚再继续。
