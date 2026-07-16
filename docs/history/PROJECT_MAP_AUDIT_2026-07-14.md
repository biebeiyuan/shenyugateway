# Shenyu Gateway 项目地图审查报告

**审查对象**:`AGENTS.md`、`START_HERE.md`、`DOCS_MAP.md`、`docs/architecture/SYSTEM_ZONES.md`、`docs/architecture/AUDIT_MATRIX.md`、`README.md`(§ Maintenance Map)、`docs/README.md` 构成的"项目地图"层。
**审查日期**:2026-07-14
**审查基线 commit**:`2ea97f7a`(master)
**定位**:这是一份时间点快照审查,不自动成为长期事实。条条结论以当时的代码/文件系统为依据,附 `文件:行号` 或可复现命令。现已归档并在 `DOCS_MAP.md` 登记;当前事实以代码、测试和现行文档为准。

## 0. 结论摘要

- 地图**分层结构合理**,准确性**经逐项核对为真**:八区 core files、`store/`·`mem_notes/`·`stars/` 包结构、START_HERE 章节锚点全部对得上,无失效链接。
- 真正问题集中在**"覆盖面归属"**:若干路由模块、admin 视图、`sessions.py`、Hisense、`conflict_books.py` 在 zone 地图里没有明确 owner 或归属不一致(见 §3)。
- 新线程入口有**三份"阅读顺序"互相不一致**的摩擦(见 §4.1)。
- 对维护**有实质性帮助**:`AUDIT_MATRIX.md` 的"已确认修复"段记录了真实修复(cold-start 重叠去重、request-log 正文最小化、复合 credential 脱敏、Memory Island 主召回失败边界),是活的、被维护的(见 §7)。
- 本报告附 `conflict_books.py` 功能解析(§5)、Hisense 现行接线状态取证(§6),供 owner 拍板两项归属决策(§9)。

## 1. 地图实际是"四层 + 维护地图",不是三份

| 层 | 文件 | 职责 |
|---|---|---|
| 协作/编码/排障口径 | `AGENTS.md` | 环境、编码、排障入口、日志判读口径 |
| 人话入口 + 任务路由 | `START_HERE.md` | 术语解释、按任务跳转、新线程最短提示词 |
| 文档状态索引 | `DOCS_MAP.md` | 现行/历史/辅助文档归属与时效 |
| 代码分区 + 桥梁 + 风险 | `docs/architecture/SYSTEM_ZONES.md` + `AUDIT_MATRIX.md` | 八区责任、跨区桥梁、风险/证据/审计顺序 |
| 逐文件索引 | `README.md` § Maintenance Map | 每个 .py 一句话说明 |
| 架构文档指针 | `docs/README.md` | architecture/ 下四份文档的入口 |

SYSTEM_ZONES 只是其中一层。后续评价针对整个体系。

## 2. 准确性验证(已逐项核对为真)✅

以下引用经文件系统核对**全部真实存在、路径正确**:

- **八区 core files 逐一比对**:包括 `store/_window_state.py`、`store/_cold_start.py`、`store/_snapshots.py`、`store/_pending.py`、`store/_request_log_history.py`、`store/_admin.py` 等,全部存在。
- **三个 package 拆分与 README 描述一致**:
  - `shenyu_gateway/store/` mixins:`_base/_sessions/_messages/_pending/_snapshots/_cold_start/_heartbeats/_cache/_room/_admin/_window_state/_request_log_history` —— 与 README Maintenance Map 描述吻合。
  - `shenyu_gateway/mem_notes/` mixins:`_helpers/_validation/_suggestions/_search/_crud` —— 吻合。
  - `shenyu_gateway/stars/` mixins:`_helpers/_chord/_scene/_weights/_crud/_recall/_activity/_review/_feedback/_logging/_render/_embedding` —— 吻合。
- **AUDIT_MATRIX "已确认修复"引用的文件存在**:`mem_notes/_search.py`、`stars/_recall.py` 等被点名引用的文件全部存在。
- **START_HERE 章节锚点真实**:`DEBUGGING_GUIDE.md § Chat Request Flow` 存在于 `DEBUGGING_GUIDE.md:172`。
- **请求链总图与代码吻合**:SYSTEM_ZONES §总体请求链(`客户端→FastAPI→ChatPipeline→prepare_messages→ContextBuilder→tool merge→UpstreamClient→response capture`)与 `chat_pipeline.py`/`prepare_messages.py` 实际调用顺序一致。

**准确性这一项可放心。** 这比多数项目的文档维护得好。

## 3. 覆盖面缺口(以 grep 取证)

### 3.1 四个路由模块无 zone 归属【Gap A】

`archive_routes.py` 有 zone 归属(列在区域七 core files),但同类另外四个路由模块**只在 README Maintenance Map 出现,在 SYSTEM_ZONES.md 与 AUDIT_MATRIX.md 的 core files 中缺席**:

| 文件 | README | SYSTEM_ZONES | AUDIT_MATRIX |
|---|---|---|---|
| `calendar_routes.py` | ✅(`README.md:125`) | ❌ | ❌ |
| `hisense_routes.py` | ✅(`README.md:126`) | ❌ | ❌ |
| `config_routes.py` | ✅(`README.md:128`) | ❌ | ⚠️ 仅作"已确认修复"证据(`AUDIT_MATRIX.md:373,447`) |
| `admin_shell_routes.py` | ✅(`README.md:129`) | ❌ | ❌ |
| `archive_routes.py` | — | ✅(区域七) | — |

证据:`grep -rn 'calendar_routes\|hisense_routes\|config_routes\|admin_shell_routes' docs/architecture/SYSTEM_ZONES.md` 零命中;`gateway.py:25-37` 确认五个 router 都在装配层注册。

**问题**:同构模块被区别对待(archive_routes 有家,其余没有)。新线程无法从地图回答"某路由归哪个区"。

### 3.2 admin 视图基本未锚定【Gap B】

`admin/src/views/` 有 12 个 Vue 视图,SYSTEM_ZONES 只点名 `LogsView.vue`(区域八)。`grep -rn 'Mem0View\|HisenseView\|ConflictView\|SessionsView\|StarsView\|CalendarView\|ArchiveView\|RoomView\|ConfigView\|ToolErrorsView\|HomeView' docs/architecture/SYSTEM_ZONES.md` **零命中**。其余 11 个视图没有 zone 指针。新线程看 admin UI 时地图给不出"这个页面的数据归哪个区"。

### 3.3 Hisense 跨区无单一 owner【Gap C】(详见 §6)

Hisense 在三份子系统文档里都出现了(REQUEST_CONTEXT 的 slow/heartbeat 层与 `hisense_heartbeat` 数据源;MEMORY_ROOM:212 "Room is the third context path alongside normal and hisense";AUDIT_MATRIX 的 hisense 测试与配置密钥),但 `hisense_routes.py` + `HisenseView.vue` 在 SYSTEM_ZONES **完全缺席**,且 Hisense 代码横跨区域一/二/五/八,没有单一 owner。这是地图最难落点的一个 feature。

### 3.4 `sessions.py` 未被任何 zone 列出【Gap D】

证据:`grep -rn 'sessions' docs/architecture/SYSTEM_ZONES.md` 零命中(exit 1)。README 把 `sessions.py` 归在"Auth & sessions",描述为"session/message logging facade"。它实际是请求区(区域二)与存储区(区域七)之间的桥,但 zone 地图没放它。

### 3.5 `conflict_books.py` 双重归属【Gap E】(详见 §5)

- `docs/architecture/SYSTEM_ZONES.md:227`:列在**区域六**(记忆、召回与外部数据)core files。
- `README.md:101`:归在 **Durable archive** 段(对应区域七语义)。

两份文档把它放进两个不同区。新线程会困惑它到底是"记忆数据源"还是"持久化 CRUD"。

### 3.6 Room 跨两个 zone【Gap F】

`room_tools.py` 在区域四(工具),`room_*.py` 在区域六(记忆/外部数据)。README 另有专门"Room mode"段(5 个文件)。拆分本身可能合理(工具入口 vs 内容),但地图没写明"Room 内容归区域六、工具入口归区域四",新线程要自己拼。

## 4. 新线程清晰度摩擦

### 4.1 三份"阅读顺序"互相不一致【Gap G】

仓库里存在三份不同的推荐阅读顺序,顺序与成员都不一致:

| 来源 | 顺序 |
|---|---|
| `DOCS_MAP.md:7-13` §新线程入口 | AGENTS → START_HERE → **README** → SYSTEM_ZONES → DESIGN → DEBUGGING_GUIDE → LOGS_GUIDE |
| `README.md:13-21` §新线程阅读顺序 | START_HERE → AGENTS → **DOCS_MAP** → SYSTEM_ZONES → README §Maintenance Map →(改内核前)DESIGN →(按需)DEBUGGING →(忘记日志)LOGS |
| `START_HERE.md:93-99` 最短提示 | 仅 AGENTS + START_HERE,其余"见 DOCS_MAP.md" |

差异点:README 把自己放第 4、DOCS_MAP 放第 2;DOCS_MAP 把 README 放第 3、且不列自己;DESIGN 在一个里是固定第 5、在另一个里是"改内核前才读"。**不算大错,但认真新线程读三遍会得到三个优先级**,这是"排查清不清晰"的实打实摩擦。

### 4.2 START_HERE 简称指 AUDIT_MATRIX 区域需推断【Gap H】

START_HERE 任务表写"`docs/architecture/AUDIT_MATRIX.md` 的上下文区""的供应商区",但 AUDIT_MATRIX 实际标题是 `## 区域三:上游协议与供应商适配`(`AUDIT_MATRIX.md:86`)、`## 区域五:上下文窗口与 Memory Island`(`AUDIT_MATRIX.md:160`)。简称能猜对,但不是精确锚点。minor,但可消除。

### 4.3 README Maintenance Map 与 SYSTEM_ZONES 重叠【Gap I】

README 逐文件给 one-liner,SYSTEM_ZONES 按 zone 给子集。DOCS_MAP(`DOCS_MAP.md:19-29` 内容归属表)明确写了二者分工(README 不放子系统完整设计、SYSTEM_ZONES 不重复文件清单),边界基本守住,但实际重叠仍大。可接受,但可互注"对方为补充"。

## 5. `conflict_books.py` 专题

### 5.1 它是什么(取证 `shenyu_gateway/conflict_books.py:3-16` docstring)

"矛盾书":一个 Supabase 后端服务(`ConflictBookService`),存你(在 admin UI)手动裁剪、定稿的争吵原文。三张表:`shenyu_conflict_books` / `shenyu_conflict_annotations` / `shenyu_conflict_reads`。

**硬规则(在 `conflict_books.py` 内强制,因为"no other layer may bypass them")**:
- `original_text` 创建时写一次,**永不改**——update 路径显式丢弃它(`USER_EDITABLE_FIELDS` 不含它,`conflict_books.py:27`)。
- Shenyu 的批注**只追加**:无 update/delete 方法(`conflict_books.py:158` 注释"不可改、不可删")。
- 每次 `shenyu_conflict_read` 调用追加一行 read-log,计数显示在书架("翻过几次")。
- **矛盾书正文绝不自动注入上下文**;只有书架块(书名+状态)是被动呈现(`render_conflict_shelf`, `conflict_books.py:223-240`,标题与状态 only)。

### 5.2 谁在用它(grep 取证)

引用 `conflict_books` / `ConflictBook` 的文件:
- `shenyu_gateway/context_builder.py`、`context_layers.py` —— 把书架块渲染进 **slow 上下文层**(区域六/五)。
- `shenyu_gateway/gateway_tools.py` —— `shenyu_conflict_read` 工具,让 Shenyu 主动翻开某本(区域四)。
- `shenyu_gateway/room_tools.py` —— 引用矛盾书(区域四 Room 工具)。
- `shenyu_gateway/archive_routes.py` —— 归档路由引用(区域七)。
- `admin/src/views/ConflictView.vue` + `admin/src/api/archive.ts` —— admin 整理书架(区域八)。
- `tests/test_conflict_and_archive.py`、`tests/test_gateway_tool_registry.py` —— 测试。
- `docs/architecture/REQUEST_CONTEXT.md`、`docs/architecture/SYSTEM_ZONES.md` —— 现行文档(区域六)。

### 5.3 归属分析与建议

`conflict_books.py` 是**混合体**:它自带 Supabase CRUD + 数据不变量(看似区域七持久化),但**功能角色是"记忆数据源"**——喂 slow 层、经 gateway tool 呈现、不自动注入(实为区域六记忆/召回语义)。它**不是** fire-and-forget 归档(与 `chat_archive`/`heartbeat_archive` 不同),所以 README 把它放进"Durable archive"段是归类不当。

**建议**:
- 代码归属**区域六**(记忆数据源),SYSTEM_ZONES 维持现状即可。
- README `:101` 把 `conflict_books.py` 从"Durable archive"移出,归入"Memory data sources"(或与 Room 一组),并在其 one-liner 注明"自带持久化不变量,见 `conflict_books.py:8-15`"。
- 不在区域七另设副本,消除双重 owner。

## 6. Hisense 专题

### 6.1 现行接线状态取证(关键:它是活代码,不是死代码)

owner 直觉"很久没用/没维护",需与代码事实分开看。grep 证明 Hisense 运行时分支是 **load-bearing 的活代码**:

- **装配层**:`gateway.py:37` `import build_hisense_router`;`gateway.py:687` `build_hisense_router(...)` 注册路由;`gateway.py:752-765` 在 `/v1/models` 暴露独立的 `hisense_upstream`。
- **独立 upstream**:`gateway.py:361-398` `_upstream_for_hisense(is_hisense)`、`_is_hisense_client(client_name)`、`_is_hisense_session`。检测键 off `client_name == "海信"`(且 config `hisense_client_name`)。
- **请求编排**:`chat_pipeline.py:55` `upstream_for_hisense` 是必填 dep;`chat_pipeline.py:236` `request_upstream = meta.get("upstream") or self.upstream_for_hisense(meta.get("is_hisense"))` —— **每个请求**都走这条选择。
- **消息准备**:`prepare_messages.py:384` `is_hisense = deps.is_hisense_client(client_name)`;`:440` 取独立 upstream;`:616` 写入 `meta["is_hisense"]`;`:495` `and not is_hisense` 控制某分支。
- **上下文构建**:`context_builder.py:122` `is_hisense = self.is_hisense_client(...)`;`:126` `consume_pending=... and not is_hisense`(心跳消费对 hisense 不同);`:155` `want_conflict = (not is_hisense)`(**矛盾书架对 hisense 跳过**);`:178-180` hisense notebook + last wake recap;`:340-393` `_hisense_heartbeat_context`/`_hisense_notebook_items`/`_hisense_last_wake_recap` 专用方法。
- **上下文层渲染**:`context_layers.py:96-98` `## 海信线程心跳` 块仅 `is_hisense` 时注入。
- **覆盖面**:18 个 .py 引用 hisense;`admin/src/router/index.ts:49` `HisenseView.vue` 仍在路由注册;`MEMORY_ROOM.md:212` "Room mode is the third context path (alongside normal and hisense)"。

### 6.2 "没维护"与"load-bearing"的区分(事实 vs 直觉)

- **事实(代码证明)**:Hisense 是一条**专属上下文路径**——独立 upstream、独立心跳池 `hisense_heartbeat`、独立 notebook、跳过矛盾书架。检测逻辑 `_is_hisense_client` **每个请求都在执行**,无论是否有 hisense client 连入。
- **直觉(owner)**:admin Hisense 页面很久没碰 / 当前没有 client 发 `client_name=海信`。这指向的是**"未被触发使用"**,不是"代码已死"。
- **推论(待验证)**:若 `hisense_client_name` 为空且无 client 标识为海信,则 hisense 分支永不激活,但检测开销与代码耦合仍在每个请求的关键路径上。

### 6.3 选项与建议

| 选项 | 含义 | 风险 | 何时选 |
|---|---|---|---|
| A. 声明 legacy 但保留 | 文档标注 Hisense 为"专属上下文路径,当前无 client 触发,保留以待重启";地图补跨区触点 | 低 | owner 纠结 / 短期不确定是否重启 → **推荐** |
| B. 完全移除 | 删 `hisense_routes`+`HisenseView`+`context_builder` hisense 分支+`prepare_messages` 分支+config/schemas 字段+测试 | 高(动核心) | 确定永不重启 → 现在不建议 |
| C. 保留并补地图 owner | 不改行为,仅在地图注明 Hisense 触点分布在区域一(装配)/二(编排)/五(上下文)/八(admin) | 极低 | 无论 A/B 都应做的文档层修复 |

**建议**:选 A + C。即便未来倾向 B,也应先有 C 的跨区触点清单,否则移除时极易漏删 `context_builder.py` 里的 hisense 分支与 `prepare_messages.py:495` 这类条件,留下半死状态。

## 7. 对维护的价值评估:有,且是实质性的

1. **"分区+桥梁+审计矩阵"三件套模型正确**:把"系统怎样分区"(SYSTEM_ZONES)与"每区确认了什么/待验证什么"(AUDIT_MATRIX)分离,正合 AGENTS.md 要求的"已证实/推测/待验证分开"。AUDIT_MATRIX"已确认修复"段记录真实修复且**被持续维护**,说明地图是活的不是摆设。
2. **DOCS_MAP 防止历史设计稿当现成事实**:显式标了 `SYSTEM_INVENTORY.md`、`*_REVIEW*.md`、`REFACTOR_PLAN.md`、`OPTIMIZATION_PLAN.md` 的时效,对有 8 份设计稿+2 份审查快照的仓库是关键护栏。
3. **AGENTS 把跨工具规则放仓库**(而非某模型全局记忆),符合其自身声明。
4. **START_HERE 人话术语段**(gateway/client/mixed tool、pending transcript、broker)质量高,把易误解的机制讲清了。

问题不是"地图没用",而是"几处没覆盖到、入口优先级有分歧"。修掉更值。

## 8. 优化清单(按性价比)

| # | 改动 | 解决 | 工作量 | 风险 |
|---|---|---|---|---|
| 1 | 三份阅读顺序统一为**一份权威列表**(放 DOCS_MAP),README/START_HERE 改"见 DOCS_MAP" | Gap G | 小 | 无 |
| 2 | SYSTEM_ZONES 加"路由归属规则":`*_routes.py` 归其功能所属区;或给 calendar/hisense/config/admin_shell 四路由各补一行 | Gap A | 小 | 无 |
| 3 | `conflict_books.py` 单一归属区域六,README `:101` 移出"Durable archive" | Gap E | 小 | 无 |
| 4 | `sessions.py` 补进区域一或区域七 core files(建议区域七,或标注为跨区桥) | Gap D | 极小 | 无 |
| 5 | START_HERE 把"上下文区/供应商区"改"AUDIT_MATRIX 区域三/区域五"精确名 | Gap H | 极小 | 无 |
| 6 | 区域八加 admin views 归属规则:"数据属区域六的视图(Mem0/Stars/Room)归该区语义,其余归区域八" | Gap B | 小 | 无 |
| 7 | Hisense:选 A+C,在地图补跨区触点清单(§6.3),文档标注 legacy | Gap C | 中 | 低 |
| 8 | (可选)给 README Maintenance Map 每行加 zone 标签,形成"文件→zone"反向索引,从根上消除跨区歧义 | E/F 通用 | 中 | 无 |

1/2/4/5 是零风险纯校准;3/6 需一次归属判定;7 需 owner 拍板 Hisense 走向。

## 9. 待 owner 拍板项

1. **`conflict_books.py` 归属**:本报告建议区域六(记忆数据源)+ README 移出归档段。是否采纳?
2. **Hisense 走向**:A(声明 legacy 保留)/B(完全移除)/C(仅补地图 owner)。当前数据支持 A+C,但 B 的决定权在 owner 是否确定"永不重启 hisense 线程"。
3. **`sessions.py` 落点**:区域一(入口)还是区域七(持久化)?它兼具请求与存储两面。
4. **是否采纳第 1 项"单一权威阅读顺序"**:若采纳,以 DOCS_MAP 版为准还是 README 版为准?

## 附 A. 可复现验证命令

```bash
# 路由模块是否在 zone 地图(预期:仅 archive 间接出现)
grep -rn 'calendar_routes\|hisense_routes\|config_routes\|admin_shell_routes' \
  docs/architecture/SYSTEM_ZONES.md docs/architecture/AUDIT_MATRIX.md

# sessions.py 是否被 zone 列出(预期:零命中)
grep -rn 'sessions' docs/architecture/SYSTEM_ZONES.md

# conflict_books 双重归属(预期:SYSTEM_ZONES 区域六 + README Durable archive)
grep -rn 'conflict_books' docs/architecture/SYSTEM_ZONES.md README.md

# admin 视图是否锚定(预期:仅 LogsView)
grep -rn 'Mem0View\|HisenseView\|ConflictView\|SessionsView\|StarsView\|CalendarView\|ArchiveView\|RoomView\|ConfigView\|ToolErrorsView\|HomeView' \
  docs/architecture/SYSTEM_ZONES.md

# Hisense 是否活代码(预期:gateway/chat_pipeline/prepare_messages/context_builder 大量命中)
grep -rn 'hisense' gateway.py shenyu_gateway/chat_pipeline.py shenyu_gateway/prepare_messages.py shenyu_gateway/context_builder.py shenyu_gateway/context_layers.py

# conflict_books 被谁用
grep -rln 'conflict_books\|ConflictBook' shenyu_gateway/ admin/src/ tests/ docs/

# 三份阅读顺序
grep -n '阅读顺序\|先读\|入口' README.md DOCS_MAP.md START_HERE.md
```

## 附 B. 本报告与现行文档的关系

- 本报告是**时间点快照**,不修改任何现行文档,也不进入 DOCS_MAP 现行文档表。
- 后续已采纳或修正的结论记录在对应现行文档中;本文件归 `docs/history/`,只用于追溯当时的审查基线和判断过程。
- 落地前请按 AGENTS.md"Mechanical Change Checklists"与"先对齐再改"原则,确认 §9 四项决策后再动 SYSTEM_ZONES/README。
