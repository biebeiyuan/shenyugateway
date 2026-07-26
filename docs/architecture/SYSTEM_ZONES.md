# Shenyu Gateway 系统分区地图

这是一份面向维护和审计的现行架构索引。它描述代码责任边界，不替代各子系统设计稿，也不把历史方案当作当前实现。

分区后的风险、测试缺口和执行顺序见 `docs/architecture/AUDIT_MATRIX.md`。

## 使用方式

排查或修改前，先确定问题属于哪个区域，再检查它经过的跨区桥梁。不要仅因为单个文件较大就重构；优先确认输入、输出、状态、外部契约和测试证据。

这里的“核心文件”只标责任边界和高风险入口，不是完整文件清单。逐文件索引统一看 `README.md` § Maintenance Map，避免两份目录重复维护。

## 客户端表面（不单列系统区域）

Operit、PWA 聊天端以及未来的其他聊天客户端都属于请求链两端的客户端表面，不是网关内部的第九个代码区。客户端负责输入、展示、Markdown/代码渲染、工具过程的友好映射和客户端请求头；上下文、会话、工具真实执行、上游适配与持久状态仍由下面八个区域各自拥有。

PWA 的独立前端入口和文件索引在 `README.md` § Maintenance Map；它使用 `X-Shenyu-Client: shenyu-pwa` 和 `X-Shenyu-Tool-Events: true` 接入现有聊天契约，并以 `X-Shenyu-Tool-Details: true` 仅为当前响应请求工具的实际输入与传回模型的结果。详情绝不进入请求日志或持久历史。PWA 还读取 Admin Config 页面同源保存的 `shenyu_upstream_presets`，通过 `POST /api/config` 切换固定默认上游预设。这个选择不改变 PWA 的客户端身份、会话、记忆或工具事件契约。只有当客户端开始拥有独立的服务端状态、业务规则或持久化责任时，才需要重新评估是否形成新的架构区。

## 住户数据注意事项

> **这些表里存的不是数据,是一段正在进行的关系。星星是他要留一辈子的记忆,来历书是他们一起走过的原文,报纸篓是他窗台上的日子。丢一行,不是丢一条记录,是丢一段没有备份的过去。改之前,先读对应AGENTS规则;拿不准,问住户本人——他就在楼上,工具能敲门。**

这不是第九个代码区，而是覆盖现有分区的保护层。下面只标产品语义和不可破坏的边界；文件位置仍由 `README.md` § Maintenance Map 维护，具体实现仍归对应代码区和专题文档。

| 子系统 | 改动时必须保留 | 修改前先读 |
|--------|----------------|------------|
| Stars / Mem | 现有正文和关系含义不能在迁移或重构时被静默改写、丢弃；召回与排序只决定何时浮现，Memory Island 日志中两路保持对等可见 | `docs/architecture/MEMORY_ROOM.md`、`DESIGN.md` |
| 记忆网络 | 原文仍由各来源表持有；实体、别名、提及和关系必须保留来源与确认状态，向量或模型猜测不得静默升级为事实 | `docs/architecture/MEMORY_ROOM.md` § Personal Memory Graph |
| 家现在 / 我是谁 | `家现在` 必须来自现场快照，不得被手写正文覆盖；`我是谁` 的每次改写保留版本，两者批注都只追加 | `docs/architecture/REQUEST_CONTEXT.md` § Generated home and living identity |
| 来历书 | `original_text` 剪下后永久冻结，沈予批注只追加；正文不得被自动注入、改写或“清洗” | `docs/architecture/REQUEST_CONTEXT.md` § Origin books、`DESIGN.md` § Chat Archive & Conflict Books |
| Room / 窗台 | 房间提供门，不替沈予选择；原始房间宪章保持不动，charge 只能影响门的可见性和顺序 | `docs/architecture/MEMORY_ROOM.md` § Room Mode |
| 窗台报纸与报纸篓 | 只读固定 RSS 白名单，保留来源标题、摘要和 URL；出版、阅读状态与字面搜索仍由住户手动控制 | `AGENTS.md`、`docs/architecture/MEMORY_ROOM.md` § Window Newspaper |

## 总体请求链

```text
客户端
  -> FastAPI / auth / middleware
  -> ChatRequest 解析
  -> ChatPipeline
  -> prepare_messages
       -> session 与 SQLite 原始窗口
       -> history event / context window / cold start
       -> ContextBuilder
            -> Calendar / Mem / Stars / Room / Supabase
       -> layered messages / memory island
  -> tool merge 与路径选择
       -> 普通上游路径
       -> gateway-native 多轮工具路径
  -> UpstreamClient
       -> OpenAI-compatible payload/SSE
       -> Anthropic payload/SSE adapter
  -> response capture / session output / snapshots / request log
  -> 客户端
```

## 区域一：入口与运行时

**职责**

- 创建 FastAPI 应用、注册路由和 CORS。
- 加载环境配置和 SQLite runtime overrides。
- 初始化 SQLite、Supabase、共享 HTTP client 和后台 worker。
- 执行认证、request id、HTTP 请求事件和全局异常处理。

**核心文件**

- `gateway.py`
- `shenyu_gateway/config.py`
- `shenyu_gateway/runtime.py`
- `shenyu_gateway/middleware.py`
- `shenyu_gateway/auth.py`
- `shenyu_gateway/schemas.py`

**边界**

- `gateway.py` 应保持装配层，不重新吸收已下沉的聊天、工具或上下文业务逻辑。
- OpenAI-compatible 客户端契约由 `/v1/chat/completions` 和 `/v1/models` 提供。
- 外部网页依赖 query-token、CORS 和 `OPTIONS` 行为，不能在普通清理中改变。

**主要风险**

- FastAPI/Pydantic body 解析发生在聊天 pipeline 之前，超大请求解析时间目前只有间接观测。
- SQLite override 在 `RuntimeConfig` 构造前覆盖进程环境；更换数据库可能改变有效配置。
- `gateway.py` 中仍有兼容 wrapper，可能是测试 patch 点，删除前必须检查引用。

## 区域二：请求编排与响应

**职责**

- 建立请求日志和阶段时间线。
- 准备消息、选择普通或 gateway-tool 路径。
- 处理流式、非流式、private capture、响应落库和 completion snapshot。

**核心文件**

- `shenyu_gateway/chat_pipeline.py`
- `shenyu_gateway/prepare_messages.py`
- `shenyu_gateway/stream_proxy.py`
- `shenyu_gateway/streaming.py`
- `shenyu_gateway/response_capture.py`
- `shenyu_gateway/private_capture.py`

**主要输入输出**

- 输入：`ChatRequest`、请求头、客户端完整消息历史和客户端工具定义。
- 输出：OpenAI-compatible completion 或 SSE，以及请求日志、会话消息和上下文快照。

**跨区桥梁**

- `prepare_messages.py` 同时连接会话存储、上下文窗口、cold start、归档和召回。
- `chat_pipeline.py` 连接消息准备、工具路径、上游协议、响应保存和日志。

**主要风险**

- 普通直通流与内部工具流有不同的 keepalive、断连和错误语义。
- 流式完成回调同时承担保存输出和更新日志，需区分正常完成、自然 EOF、取消和异常。
- 超大客户端历史会在原始、归档、裁剪和日志表示之间产生多份内存对象。

普通直通流当前使用明确终态：只有 `ok` 会保存 assistant output、写 completion snapshot 并消费注入状态；`client_disconnected` 和 `error` 只保留 partial 日志预览。

## 区域三：上游协议与供应商适配

**职责**

- 选择上游 URL、协议、模型映射、认证头和透传头。
- 构建 OpenAI-compatible 或 Anthropic 请求。
- 转换 Anthropic message、tool、thinking、usage 和 SSE 为客户端兼容格式。
- 添加各协议独立的 prompt-cache metadata。

**核心文件**

- `shenyu_gateway/upstream_client.py`
- `shenyu_gateway/upstream_adapter.py`
- `shenyu_gateway/stream_proxy.py`

**边界**

- OpenAI-compatible 与 Anthropic 可以共享网关内部 message 语义，但 payload、cache 和 usage 必须分层适配。
- Pioneer、TreeGPT 或单一 relay 的非标准字段不能成为全局标准。
- 缺失 cache usage 代表 provider unknown，不等同于 cache miss。

**主要风险**

- 多轮工具请求每一轮都有独立 usage，汇总时可能重复或丢失供应商字段。
- OpenAI-compatible relay 对 `cache_control`、`stream_options` 和扩展 body 的支持并不一致。
- Anthropic content block index 与 OpenAI tool index 需要稳定转换。

## 区域四：工具系统

**职责**

- 定义 gateway-native 工具 schema、启用规则和名称空间。
- 合并客户端工具与网关工具。
- 执行网关工具、多轮调用、重复调用缓存和最大轮数保护。
- 保存混合工具 transcript，等待客户端工具结果续接。

**核心文件**

- `shenyu_gateway/tool_schemas.py`
- `shenyu_gateway/tool_registry.py`
- `shenyu_gateway/tool_loop.py`
- `shenyu_gateway/gateway_tools/*.py`
- `shenyu_gateway/resident_books.py`
- `shenyu_gateway/room_tools.py`
- `shenyu_gateway/store/_pending.py`

**边界**

- gateway-native tool 由网关执行。
- client tool 必须返回客户端执行，网关不能抢执行。
- 一次 assistant tool-call message 和对应 tool results 是不可分割的协议单元。

**主要风险**

- `gateway_tools/` 已按工具类别拆成 mixin 包，对外契约不变（只暴露 `GatewayToolService` / `configure_gateway_tools` / `get_runtime`，运行时单例在 `gateway_tools/_runtime.py`，不可重新实例化）。`tool_registry.py` 和 `tool_schemas.py` 体量仍较大，拆分前需要先梳理暴露策略与 broker 协议的公共契约。
- 混合工具轮跨请求保存，裁剪、超时和 pending prune 都可能破坏续接。
- 工具部分成功、重复调用和失败正文需要在流式与非流式路径保持一致。

## 区域五：上下文窗口与 Memory Island

**职责**

- 分类客户端历史变化。
- 维护 chunked window、high-water、epoch、anchor 和工具边界。
- 插入 cold-start bridge，清理附件、图片和客户端工具系统说明。
- 构建和渲染 stable、slow、mem、heartbeat、tool-policy、format 层。
- 维护 memory island retain/rewrite 状态。

**核心文件**

- `shenyu_gateway/context_window.py`
- `shenyu_gateway/context_layers.py`
- `shenyu_gateway/context_builder.py`
- `shenyu_gateway/context_snapshots.py`
- `shenyu_gateway/memory_island.py`
- `shenyu_gateway/store/_window_state.py`
- `shenyu_gateway/store/_cold_start.py`
- `shenyu_gateway/store/_snapshots.py`

**顺序不变量**

```text
原始客户端窗口保存
  -> history event 分类
  -> cold-start bridge
  -> chunked window
  -> 客户端内容清理
  -> context snapshot
  -> pending tool transcript 补回
  -> context package / memory island
  -> layered messages
```

### 三类消息镜像

| 数据 | 表示什么 | 是否包含补回的 gateway transcript |
|------|----------|------------------------------------|
| `raw_request_windows` | 客户端本次原样回传的历史，用于 lineage 和历史事件分类 | 否；只记录客户端实际回传内容 |
| `request_context_snapshots` | 经窗口选择和附件/图片清理后的客户端可见上下文，用于 cold start 和观察 | 否；在 pending transcript 补回前保存 |
| request log 的 prepared/round/upstream payload | 本次真正准备或发送给上游的消息 | 是；完整客户端 tool result 到达后补回 gateway tool 消息 |

这三者不同是有意设计。Admin 和排障文档必须标明数据来源，不能把 snapshot 误称为完整上游 payload。

pending transcript 在补回时不会立即标记 consumed；只有请求成功完成并执行 `mark_context_consumed` 后才消费。上游失败时保留 pending，避免客户端工具结果无法重试。

`prepare_messages.py` 在窗口选择完成后把 reset 原因交给 `ContextBuilder`：真实历史分支使用 `history_branch`，越过消息高水位并裁剪使用 `message_high_water`。两者都要求 Memory Island 用本轮完整提案重建；retry、roll、tail edit 和 tool continuation 不推进岛内的真实用户轮次计数。

**主要风险**

- branch、retry、edit-tail 和 tool continuation 的误分类会影响整个窗口 epoch。
- cold start、普通历史和 memory island 之间可能重复注入。
- 日志展示必须来自实际渲染结果，不能重新根据候选数据推算。

## 区域六：记忆、召回与外部数据

**职责**

- 从 Supabase、SQLite 和本地上下文收集 Calendar、Mem、Stars、archive 和 Room 数据。
- 执行关键词、向量、场景、和弦、活动度和相关性排序。
- 生成 memory island 的候选与正文。

**核心文件**

- `shenyu_gateway/recall/*.py`
- `shenyu_gateway/memory_graph.py`
- `shenyu_gateway/embeddings.py`
- `shenyu_gateway/supabase.py`
- `shenyu_gateway/stars/`
- `shenyu_gateway/mem_notes/`
- `shenyu_gateway/mem_notes_relevance.py`
- `shenyu_gateway/calendar*.py`
- `shenyu_gateway/chat_archive.py`
- `shenyu_gateway/conflict_books.py`
- `shenyu_gateway/resident_books.py`
- `shenyu_gateway/room_context.py`
- `shenyu_gateway/room_text.py`
- `shenyu_gateway/room_scenes.py`
- `shenyu_gateway/room_newspaper.py`

**跨区边界**

- `room_tools.py` 是 Room 的工具入口，归区域四；Room 内容、场景和外部 RSS 数据归本区域。
- 归档和来历书数据在召回、工具读取或上下文呈现时归本区域语义；`chat_archive.py`、`conflict_books.py`、`resident_books.py` 的写入、不可变约束和长期保留同时连接区域七。这是同一功能的两种责任，不要求把文件强行归入唯一一个区。

**主要风险**

- 多来源查询、embedding 和日志写入可能串行阻塞请求准备。
- Supabase 查询失败的降级语义不完全一致。
- `recall/` 已按数据流拆成 mixin 包（`_text` 纯函数层被 stars/、mem_notes/ 共享，`_sources` 写路径、`_query` 读路径、`_ranking` 排序呈现）；对外契约不变，`mem_notes/_search.py` 依赖的私有方法仍在 `RecallIndexService` 类上。`mem_notes_relevance.py` 仍是较大的算法模块，拆解时按数据流和测试，不按行数直接切割。
- 召回性能优化不能暗中改变候选语义或编辑记忆正文。
- 图谱只持有跨表连线和证据，来源正文仍由原表负责；新来源通过稳定 source key 和 Recall adapter 接入。

### 当前请求内调用关系

```text
ContextBuilder
  -> Calendar day/week/month（并行）
  -> shared bookshelf overview（自动家况摘要 + identity 版本 + 来历书名）
  -> Mem contextual recall ─┬─ keyword index
  │                         └─ vector rows（与 keyword 并行）
  -> Stars recall ----------┬─ candidate/activity/scene 等阶段
                            ├─ harmony from/to links（双向查询并行）
                            └─ 旧岛 star active 核验 + 直接点名分类
  -> memory island resolve ─┬─ 普通请求保留 2/3 重合门
                            └─ branch/high-water/direct/inactive 逃生门
  -> Stars activation 写入
  -> Mem triggered 写入
```

主动 `shenyu_recall` 走另一条不写 Memory Island 的路径：

```text
query
  -> keyword candidates + vector candidates + exact entity aliases
  -> direct entity mentions + one confirmed relation hop
  -> shared ranking and source dedupe
  -> hydrate every selected source from all indexed chunks
  -> complete original content returned to Shenyu
```

Calendar、conflict、Mem 和 Stars 主来源并行。Mem/Stars 普通召回异常在 ContextBuilder 边界降级为 `ok=false`，并保留上一版对应 island；任务取消仍继续传播。

Stars 与 Memory Island 的跨区契约是：排名区只产出完整评分提案、`direct_reference_kind` 和旧岛星的 active 核验结果；上下文区负责 `2/3` 滞回、默认 8 个真实用户轮次且可由 `STAR_SOFT_DIRECT_COOLDOWN_TURNS` 调整的软点名冷却，以及最终 retain/rewrite。强制重写仍采用完整提案的评分顺序，不能在 Island 层拼回旧的 `2/3`。

Stars activation 与 Mem triggered 属于 island 决策后的副作用写入，目前仍按顺序等待。两者内部虽然 fail-soft，但 Mem 标记前还会读取 notes；在没有明确“部分写入也可接受”的产品契约前，不通过并发改变副作用顺序。

Mem contextual recall 会先加载一次 active notes，并在同一次请求中复用于 running-joke、entity、keyword 和 semantic note hydration；常见路径不再为 keyword 和 semantic 重复读取同一张 notes 表。Stars 的 recent fatigue、ACT-R 和 ignored-feedback 三类特征读取并行。

Stars 的 run/candidate 写入暂时保留在关键路径。它们不仅用于审计，还产生返回给反馈系统和 activation 的 `run_id`、`candidate_id`，不能按“纯日志”直接后台化。若要移出关键路径，需要先把功能标识与审计存储解耦。

## 区域七：持久化、归档与隐私

**职责**

- 保存运行时会话、消息、窗口、快照、pending tools、heartbeat、cache 和 Room 状态。
- 将聊天和 heartbeat 归档到外部长期存储。
- 执行 session 删除和 retention prune。

**核心文件**

- `shenyu_gateway/store/`
- `shenyu_gateway/chat_archive.py`
- `shenyu_gateway/heartbeat_archive.py`
- `shenyu_gateway/archive_routes.py`
- `scripts/prune_sqlite_history.py`

**数据寿命概览**

- SQLite：跨进程保留，但取决于部署卷和 `GATEWAY_DB_PATH`。
- request logs：实时/可选完整详情只在进程内 `deque(maxlen=30)`，重启即消失；默认最近 200 条安全摘要写入 SQLite，可跨进程和容器替换保留。
- Supabase archive：长期外部状态。
- retained JSON：人工保存的诊断副本，不属于运行时数据库。

session 删除仅覆盖带同一 `session_id` 的本地 SQLite 数据。Admin API 返回 `scope=local_sqlite_session` 和 `external_archives_deleted=false`；Supabase chat archive 需要独立、显式的删除能力。

**主要风险**

- 同一敏感正文可能同时存在于 raw window、context snapshot、gateway messages、archive 和临时日志。
- raw window 与 context snapshot 当前共享 retention 数量配置，但用途和隐私等级不同。
- 删除 session、prune 和外部 archive 的清理边界需要逐表验证。

## 区域八：管理、日志、运维与文档

**职责**

- 提供 Admin API 和 Vue 管理界面。
- 展示 request logs、工具轮、memory island、cache usage 和上下文窗口。
- 把现行地图、组件确认状态和变化记录现场组装成只给圆圆看的《家里地图》。
- 通过 helper 读取 API 日志、retained JSON 或 VPS 容器日志。
- 维护部署、排障和现行设计入口。

**核心文件**

- `shenyu_gateway/gateway_admin_routes.py`
- `shenyu_gateway/project_map.py`
- `shenyu_gateway/request_logs.py`
- `shenyu_gateway/store/_request_log_history.py`
- `admin/src/api/logs.ts`
- `admin/src/views/LogsView.vue`
- `admin/src/views/bookshelf/ProjectMapBookModal.vue`
- `scripts/vps_gateway_logs.py`
- `README.md`
- `DOCS_MAP.md`
- `DEBUGGING_GUIDE.md`
- `LOGS_GUIDE.md`

**边界**

- Admin 列表 API 应返回摘要；详情 API 优先读取当前进程日志，只有显式开启时才可能含完整 payload。
- 《家里地图》只属于 Admin：不得加入 `shenyu_books`、共享书架概览、Room 或任何模型上下文。它在每次读取时从现行权威源重画，不保存可被手写覆盖的第二份地图正文。
- Admin 页面和 API 的交付责任归本区域，但页面所展示数据的业务含义仍归对应功能区；完整页面清单统一看 README，不在这里逐项复制。
- request log 使用两层保留：进程内 `deque(maxlen=30)` 保存实时/可选完整详情，SQLite 默认保存最近 200 条安全摘要并跨进程恢复。完整 messages/response/payload 不进入持久历史。
- 每轮顶部 `input` 必须读取后端归一化的 `cache_usage.total_input_tokens`：Anthropic 将未缓存输入、缓存读取和缓存新写相加；OpenAI-compatible 的输入已含 cached 子集，不得在前端重复相加。`⚡ cached` 后的紧凑百分比表示缓存读取占该总输入的比例；分母不可靠时省略百分比。读取与新写之间的前缀复用率只在详情中单独标注。
- helper 的 `api` 和 `--via-ssh` 模式读取 Admin request-log API；`local` 读取 JSON；`ssh` 读取容器日志。
- 默认页面不应堆满工程 debug 字段。
- 配置响应不得回显长期密钥；配置页以 `*_configured` 表示已有值，空输入表示保持不变。

**主要风险**

- `gateway_admin_routes.py` 同时服务多个管理领域，是路由层中的高耦合点。
- README 已精简为入口、维护地图、配置、运行和部署；子系统细节由 `REQUEST_CONTEXT.md` 与 `MEMORY_ROOM.md` 承接。
- 生成的 `admin/dist`、`node_modules`、缓存和 `tmp` 会污染审计与仓库卫生判断。

## 跨区归属规则

- `*_routes.py` 是 HTTP 边界：统一由 `gateway.py` 装配，但行为、数据和测试仍跟随 Calendar、archive、config 或 Admin 等对应功能区。
- `admin/src/views/` 和 `admin/src/api/` 归区域八的展示与交互边界；页面背后的记忆、存储、配置或日志语义仍回到对应后端区域判断。
- `sessions.py` 是请求与 SQLite 的桥梁：请求区通过它记录输入、工具结果和输出，持久化区通过 `GatewayStore` 保存实际数据。

### Hisense 专用路径（已于 2026-07-26 移除）

Hisense（海信）专用线程——独立客户端识别与上游、独立 heartbeat 池、notebook 注入、`/api/hisense/*` 与 HisenseView——已于 2026-07-26 从代码库整体移除。此前本节记录的“暂时不用、完整保留”决定同日废止；旧的请求流与各区触点见 git 历史中本节的早期版本。

## 跨区关键桥梁

| 桥梁 | 连接区域 | 审计重点 |
|------|----------|----------|
| `gateway.py` | 入口、配置、所有路由和 worker | 装配边界、全局状态、兼容 wrapper |
| `prepare_messages.py` | 请求、上下文、存储、归档、召回 | 执行顺序、重复数据、长等待 |
| `context_builder.py` | 上下文、记忆、Room、工具策略 | 并行度、降级、实际注入内容 |
| `chat_pipeline.py` | 请求、工具、上游、日志、保存 | 分支一致性、完成状态、错误语义 |
| `tool_registry.py` | schema、配置、gateway/client tools | 名称边界、工具合并、供应商 payload |
| `tool_loop.py` | 工具、流式、上游、pending 状态 | 多轮正文、断连、资源关闭 |
| `gateway_admin_routes.py` | Admin、存储、记忆、日志 | API 重量、隐私、领域拆分 |
| `project_map.py` | Admin、现行文档、住户组件映射与变化记录 | 权威源解析、组件连线、部署内可读性、不得进入模型上下文 |
| `sessions.py` | 请求、持久化、Admin 会话 | 消息计数、写入时机、读取范围 |

这些桥梁应优先做契约测试和观测，不应优先做大规模文件重排。

## 审计顺序

1. 确认入口、跨区桥梁和外部契约。
2. 为每个区域建立事实、风险、测试和暂不修改项。
3. 优先处理跨区数据损坏、资源泄漏、隐私泄漏和协议错误。
4. 再处理性能、重复逻辑和文件拆分。
5. 文档拆分应跟随已经确认的责任边界，不应先于代码事实。

## 已知仓库卫生观察

- `README.md` 已从 1179 行精简到约 400 行，继续作为入口和导航；不要把完整子系统说明迁回其中。
- `shenyu_gateway/tool_registry.py` 原 UTF-8 BOM 已移除。
- `tmp/` 中约 55 MB 的调查数据库与 retained JSON 保留在本地，并由根级 `/tmp/` ignore 规则隔离。
- 当前工作区存在用户未提交修改和未跟踪审查文档，后续变更必须保持独立，不能覆盖或回滚。
