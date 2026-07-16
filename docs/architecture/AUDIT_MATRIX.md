# Shenyu Gateway 全仓审计矩阵

本文是分区体检的总控表。`SYSTEM_ZONES.md` 回答“系统怎样分区”，本文回答“每个区已经确认什么、还需要验证什么、先审什么”。

## 风险口径

- **P0**：已确认的敏感信息泄漏、数据损坏、认证绕过或生产不可用问题。发现后立即停止扩展审计，先隔离和修复。
- **P1**：可能破坏请求协议、上下文语义、工具轮完整性、持久化一致性或资源释放的问题。
- **P2**：性能、可观察性、维护复杂度或局部兼容风险。
- **P3**：代码卫生、文档体验和可读性问题。
- **待验证**不等于 bug。只有代码证据、测试复现或线上日志能够把它升级为“已确认问题”。

## 总览

| 区域 | 当前证据强度 | 最高待验证风险 | 测试覆盖概况 | 建议顺序 |
|------|--------------|----------------|--------------|----------|
| 入口与运行时 | 中 | P1 配置来源和大请求解析观测 | 配置与外部契约较好，body 生命周期较弱 | 4 |
| 请求编排与响应 | 中高 | P1 流式取消、空流和完成状态 | 内部工具流较强，普通直通流较弱 | 2 |
| 上游协议与供应商 | 高 | P1 双协议 usage/cache 与异常流 | adapter 测试较强 | 3 |
| 工具系统 | 中高 | P1 混合工具 transcript 完整性 | registry/loop/return format 较强 | 1 |
| 上下文与 Island | 高 | P1 事件分类、重复注入、工具边界 | trim/window/island 覆盖较强 | 1 |
| 记忆与召回 | 中 | P2 延迟、静默降级和重复查询 | 算法单测较强，跨服务性能较弱 | 5 |
| 持久化与隐私 | 中 | P1 多副本正文、删除和 retention | store 单测存在，隐私生命周期不足 | 1 |
| 管理与运维 | 中 | P1 日志详情泄密，P2 API 重量 | helper 较强，Admin 数据重量较弱 | 2 |

“建议顺序 1”包含三个并行视角：工具/上下文协议完整性、持久化隐私、跨区删除。它们应先只读核对，再决定先修哪一个。

## 区域一：入口与运行时

### 已确认事实

- FastAPI 在进入 `ChatPipeline.run()` 前完成 `ChatRequest` 解析和 Pydantic 校验。
- HTTP middleware 在路由解析前记录请求开始，在返回 `StreamingResponse` 对象时记录 HTTP 完成；它不代表 SSE 已发送完毕。
- SQLite `config_overrides` 在 `RuntimeConfig()` 构造前加载到进程环境。
- 实际配置优先级是：进程启动时 `.env` 以 `override=True` 加载，随后当前/重定向 SQLite 的 `config_overrides` 覆盖进程环境，最后构造 `RuntimeConfig`；Admin 更新再同步内存、`.env` 和 SQLite。
- 应用 lifespan 创建共享上游 HTTP client、recall worker 和 heartbeat archive worker，并在 shutdown 取消或关闭。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P1（接受风险） | 密钥同时明文持久化到 `.env` 与 SQLite override | Admin 跨容器恢复设计；API 已不回显 | 限制文件/卷/备份访问并定期轮换；迁移到外部 secret store 前不做自制加密 |
| P2 | 2000+ messages 的 body 接收、JSON 解析和 Pydantic 构造缺少独立阶段观测 | pipeline 只看到解析后的 body | ASGI 基准、内存峰值、middleware/pipeline 时间差 |
| P2 | HTTP request event 对流式请求的 `duration_ms` 只覆盖响应建立，不覆盖完整流 | middleware 调用边界已确认 | 文档和日志字段语义核对 |
| P3 | `gateway.py` 兼容 wrapper 较多 | 代码已确认 | 测试 monkeypatch 和外部 import 搜索后再判断 |

### 现有测试证据

- `tests/test_config_update.py`
- `tests/test_external_contracts.py`
- `tests/test_gateway.py`

### 暂不修改

- 不手工读取 request body 绕过 FastAPI；这会改变校验、错误响应和内存行为。
- 不删除兼容 wrapper，直到完成 import 和 monkeypatch 契约清单。
- 不在缺少迁移方案时删除 SQLite override；Coolify/容器部署可能依赖它跨重建恢复 Admin 配置。

## 区域二：请求编排与响应

### 已确认事实

- `ChatPipeline` 在消息准备后根据合并工具中是否存在 gateway-native tool 选择路径。
- 普通流、内部工具流和非流式路径分别保存响应与日志。
- 所有普通上游流均在 `finally` 关闭 `httpx.Response`。
- OpenAI-compatible 上游自然 EOF 且没有 `[DONE]` 时，网关此前不会补 sentinel；现已增加回归测试和最小修复。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P2 | 普通 OpenAI-compatible 直通流没有网关 keepalive | 当前为上游透传 | 线上代理 idle timeout 证据；避免无证据改变透传语义 |
| P2 | 大历史在 raw、archive、snapshot、prepared log 间产生多份对象 | prepare 顺序已确认 | 内存基准和对象尺寸采样 |

### 现有测试证据

- `tests/test_gateway_streaming.py`
- `tests/test_gateway_tags.py`
- `tests/test_response_capture.py`

### 暂不修改

- 不统一普通流和内部工具流实现；二者的代理与重放责任不同。
- 不在缺乏断连产品语义时删除部分正文或强制保存部分正文。

## 区域三：上游协议与供应商适配

### 已确认事实

- OpenAI-compatible 与 Anthropic 共享内部消息表示，但由 adapter 构建不同 payload。
- Anthropic SSE、content blocks、tool index、thinking 和 usage 在网关内转换。
- OpenAI 与 Anthropic 的 cache enable、TTL 和 payload 标记分别配置。
- OpenAI-compatible 可携带 relay-specific extra body 和允许列表中的透传头。
- 请求侧 `prompt_cache` 只说明网关是否实际插入 breakpoint、使用的协议与 TTL，不证明供应商命中缓存。
- gateway-managed 工具链在 `internal_tool_rounds[].prompt_cache` 保存每轮最终 payload 的 marker 数量、断点路径和前缀指纹；这些是网关出站结构证据，不是供应商命中证据。
- 响应侧 completion usage 使用 OpenAI-compatible 基础 token 字段；Anthropic 的 cache read、cache write 和 TTL 创建明细同时保留为扩展字段，供日志诊断使用。
- `cache_usage` 是从每轮 provider-reported usage 派生的请求级摘要，不是计费估算，也不能在字段缺失时证明 cache miss。

### 标准字段边界

| 层级 | 字段/责任 | 解释 |
|------|-----------|------|
| 请求意图 | 顶层及 `internal_tool_rounds[].prompt_cache` | 网关每轮实际构造的 breakpoint、指纹和 `cache_control_marker_count`；属于 outbound/attempted 事实 |
| 供应商原值 | 每轮 `usage` | 保留上游返回的 token/cache 字段；不跨供应商伪造精确率 |
| 兼容 token | `prompt_tokens`、`completion_tokens`、`total_tokens` | Anthropic 响应转换成 OpenAI-compatible 客户端形状 |
| 缓存读取 | `cache_read_input_tokens` 或 `prompt_tokens_details.cached_tokens` | 仅在供应商返回对应字段时代表 reported read |
| 缓存写入 | `cache_creation_input_tokens`、`cache_creation` | Anthropic/兼容 relay 返回的 reported write 与 TTL 明细 |
| 请求摘要 | `cache_usage` | 多轮 read/write 数值汇总；当前布尔值只表示数值是否大于 0 |
| 未知状态 | usage 缺少缓存字段 | provider unknown；不得解释为确定未命中 |

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P2 | relay 不支持 `stream_options.include_usage` 或 OpenAI `cache_control` | 兼容 relay 行为不统一 | 按上游 scope 记录能力，不做全局假设 |
| P2 | Anthropic 四个 breakpoint 在层缺失或 island 变化时的位置漂移 | cache path 逻辑存在 | payload snapshot 测试组合 |

### 现有测试证据

- `tests/test_upstream_adapter_stream.py`
- `tests/test_upstream_passthrough_headers.py`
- `tests/test_gateway_hisense_context.py`
- `tests/test_gateway_streaming.py`
- `tests/test_gateway_store.py`

### 暂不修改

- 不根据某个 relay 的 usage 缺失推断全局 cache miss。
- 不把 Pioneer、TreeGPT 或其他 relay 字段写入通用 completion schema。
- 不把 `prompt_cache.enabled=true` 显示成供应商已缓存或已节省费用。

## 区域四：工具系统

### 已确认事实

- gateway-native tool 通过名称空间识别并由网关执行。
- client tool 不由网关执行。
- 混合调用会保存 pending transcript，下一次客户端带回 tool results 后重建完整消息序列。
- 内部工具流有最大轮数、重复调用缓存、工具错误分类、keepalive 和断连检查。
- 当前 34 个公开 gateway tool schema 全部存在 handler；唯一未公开 handler 是明确隐藏的兼容工具 `shenyu_surface_passages`。
- expanded full/daily 与 broker full/daily surface 的公开集合已运行时对账；broker 只公开统一入口 `shenyu_gateway_tool`。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P2 | broker 人工描述中的参数说明可能与 schema 漂移 | 描述与 schema 分开维护 | 对高风险工具增加描述/schema 样本 |

### 现有测试证据

- `tests/test_gateway_tool_registry.py`
- `tests/test_gateway_streaming.py`
- `tests/test_gateway_tools_return_format.py`
- `tests/test_gateway_tools_notebook.py`
- `tests/test_gateway_tools_windowsill.py`

### 暂不修改

- 不为了文件大小重写稳定工具循环。
- 不合并 gateway 和 client tool 的错误处理语义。

## 区域五：上下文窗口与 Memory Island

### 已确认事实

- 原始客户端窗口在裁剪前保存。
- cold-start bridge 在 chunked-window 选择前插入。
- 附件、客户端工具系统消息、旧安装结果和图片在窗口选择后清理。
- context snapshot 在 pending gateway transcript 补回前保存。
- memory island 在 context package 构建时结合上一状态决定 retain/rewrite。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|

### 现有测试证据

- `tests/test_gateway_trim.py`
- `tests/test_memory_island.py`
- `tests/test_gateway_store.py`
- `tests/test_context_window_observer.py`

### 暂不修改

- 不改变裁剪算法参数或顺序，直到每种历史事件都有旧行为样本。
- 不用候选数据重建日志中的“实际发送小岛”。

## 区域六：记忆、召回与外部数据

### 已确认事实

- Calendar day/week/month 查询已并行。
- 普通 context package 的 Calendar、conflict books、Mem 和 Stars 有并行 gather 阶段。
- 多个外部来源失败会降级为空结果，部分路径记录 trace，部分仅吞掉异常。
- Supabase 使用共享 `httpx.AsyncClient`，默认请求 timeout 为 30 秒。
- chat archive 通过保留强引用的后台 task 写入，不阻塞聊天主路径。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P2 | 辅助召回特征失败多以空值降级，日志难区分“无特征”与“查询失败” | 主 Mem/Stars 候选异常会抛到 builder 并保留旧岛；semantic/harmony/ACT-R/fatigue 等辅助通道 fail-soft | 为辅助通道增加 failure flags/trace，不改变评分降级语义 |
| P2 | 单个 Supabase/embedding 请求最长可阻塞 context build 约 30 秒 | client timeout 已确认 | 分阶段耗时日志和软超时策略评估 |
| P2 | Stars/Mem 内部可能重复查询同一候选或形成 N+1 | Mem active rows 已复用于 keyword/semantic hydration；Stars activity 三路和 harmony 双路已并行；逐项 activation/update 仍串行 | request-scoped query trace 和真实候选数量 |
| P2 | 背景日志、activity、feedback 写入可能处于关键路径 | Stars run/candidate 写入产生功能所需 ID，不能直接后台化；activation/triggered 仍同步 | 先解耦功能标识与审计日志，再评估后台写入 |

### 现有测试证据

- `tests/test_recall.py`
- `tests/test_mem_notes.py`
- `tests/test_star_memory.py`
- `tests/test_star_rrf_scoring.py`
- `tests/test_star_harmony.py`
- `tests/test_star_scene_cache.py`
- `tests/test_calendar.py`

### 暂不修改

- 不通过减少候选、删除召回通道或跳过 embedding 来伪造性能提升。
- 不让分类、维护或性能任务编辑已有记忆正文。

## 区域七：持久化、归档与隐私

### 已确认事实

- SQLite 同时保存 gateway messages、raw windows、context snapshots、pending turns 和多类运行状态。
- raw window 与 context snapshot 使用同一个 retention 配置值。
- request logs 的实时层是进程内 bounded deque；SQLite 另存有界安全摘要，完整 payload 仍随进程消失。
- chat archive 将去重后的 user/assistant 正文写入 Supabase。
- session 删除代码逐表删除 SQLite session 关联数据；长期 Supabase archive 是独立边界。
- Dockerfile 不声明 volume；默认 `/app/data/shenyu_gateway.db` 和 Admin 写入的 `/app/.env` 只有在 Coolify 显式挂载对应路径时才跨容器替换保留。
- 完整 request-log payload 已改为 `GATEWAY_LOG_FULL_PAYLOADS=true` 显式 opt-in；默认只保留摘要、预览和计数。
- request-log 安全摘要已进入 SQLite `request_log_history`，默认全局保留最近 200 条；完整 Messages、Upstream payload、Response、图片、原始 Thinking/signature 在落库前统一剔除。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P2 | raw window/context snapshot 共用 retention，无法按隐私价值分别配置 | 配置已确认 | 是否需要解耦的运维证据 |

### 现有测试证据

- `tests/test_gateway_store.py`
- `tests/test_conflict_and_archive.py`
- `tests/test_config_update.py`
- `tests/test_vps_gateway_logs.py`

### 暂不修改

- 不把 request logs 直接完整持久化到 SQLite。
- 不扩大正文保存范围来改善可观察性。
- 不仅因为正文重复就删除 raw window、snapshot 或 pending 数据；它们分别承担事件分类、cold start/calendar 和工具协议恢复职责。

## 区域八：管理、日志、运维与文档

### 已确认事实

- Admin 日志列表返回摘要，详情 API 返回单条完整信息。
- Admin 与 helper 的 API 模式合并读取进程内 request-log deque 和 SQLite `request_log_history`；同一 id 优先使用当前进程中的实时版本。
- helper `local` 读取 retained JSON，`ssh` 读取容器 stdout/stderr，它们不是同一底层数据。
- README 已从 1179 行精简到约 400 行；子系统细节和八区地图已迁入 `docs/architecture/`。
- README Maintenance Map 是顶层运行模块与独立 Admin 视图的反向索引；package 内部 mixin 继续由 package 条目汇总，`tests/test_project_map.py` 检查新增漏项和失效路径。

### 待验证风险

| 优先级 | 风险 | 当前证据 | 所需验证 |
|--------|------|----------|----------|
| P2 | 日志列表是否仍复制过多 memory island、timeline 和 round 摘要 | 返回字段已确认 | 序列化体积基准 |
| P2 | `gateway_admin_routes.py` 聚合多个领域，修改时回归面较大 | import/call 依赖已确认 | 按路由领域拆分建议，不立即搬文件 |
| P3 | README、DEBUGGING 和专题稿存在重复事实漂移 | README 子系统章节已迁出，文档职责与历史状态已建立 | 后续改动按 DOCS_MAP 内容归属维护 |

### 现有测试证据

- `tests/test_vps_gateway_logs.py`
- `tests/test_gateway_store.py`
- `tests/test_external_contracts.py`
- `tests/test_project_map.py`

### 暂不修改

- 不删除历史设计稿。
- 不一次性拆分 Admin 路由和 README；先迁移重复事实并保留链接。

## 第一轮深入审计包

建议将下一轮工作限定为一个完整、但跨区一致的“请求完整性包”，而不是零散 bug：

1. **客户端历史到实际上游 payload**：覆盖普通、gateway tool、client tool、混合工具和 cold start。
2. **双协议响应生命周期**：覆盖流式、非流式、空流、异常 EOF、取消、usage 和资源关闭。
3. **日志与持久化镜像**：确认 raw window、snapshot、round payload、assistant output 各自表示什么。
4. **敏感字段红线**：证明上述日志与 helper 不泄漏认证和工具秘密。

完成这个审计包后，再进入召回性能包和文档迁移包。这样每次修改仍然聚焦，但不会失去跨区逻辑。

## 已确认修改

### Admin 日志详情 credential 脱敏

- 文件：`shenyu_gateway/gateway_admin_routes.py`
- 行为：所有通过日志详情 API 暴露的嵌套 dict/list 和 URL query 会按明确 credential 键递归脱敏。
- 覆盖：`authorization`、`api_key`、`token`、`secret`、`password`、`private_key` 等标准键名及连字符变体。
- 保留：消息正文、普通工具参数、路由字段和内部 request log 原始排障数据。
- 连带保护：helper 的 `--raw` 和 `--save` 来源是公开详情 API，因此接收到脱敏后的结构。
- 测试：`tests/test_gateway_store.py` 验证嵌套字段、URL token、原对象不变和普通正文保留。
- 验证：Admin/store、helper、外部契约、流式和 adapter 相关测试共 108 个通过。

### Session-scoped SQLite 删除完整性

- 文件：`shenyu_gateway/store/_sessions.py`、`shenyu_gateway/gateway_admin_routes.py`
- 已确认问题：`tool_error_log` 和 `room_trace` 带 `session_id`，但原删除清单没有包含它们。
- 修复：删除会话时同步删除这两类诊断正文；API 明确 scope 仅为本地 SQLite，不删除外部 archive。
- 测试：根据实际 SQLite schema 自动枚举所有含 `session_id` 的表，并要求它们全部出现在删除结果中。
- 保留边界：Room 的全局 scribbles、pins、drawer notes 不带 `session_id`，不随单个会话删除。
- 验证：请求完整性、工具、协议、存储、归档和 helper 相关测试共 203 个通过。

### 双协议普通流终态完整性

- 文件：`shenyu_gateway/stream_proxy.py`、`shenyu_gateway/chat_pipeline.py`
- 已确认问题：普通流的完成回调原先在正常结束、客户端取消和上游异常时使用同一语义，pipeline 会把 partial 正文记为成功并消费 pending/cold-start 上下文。
- 修复：OpenAI-compatible 与 Anthropic 普通流统一报告 `ok`、`client_disconnected` 或 `error` 终态及错误说明。
- 提交边界：非正常终态保留 partial response preview 供排障，但不保存 assistant output、不写 completion snapshot、不消费 heartbeat、cold-start 或 pending transcript。
- 空流：仍向已建立的 SSE 客户端发送 `[DONE]` 结束连接，但日志终态为 error。
- 测试：覆盖双协议空流、异常中断、OpenAI-compatible 取消、自然 EOF 和 pipeline 不提交上下文。

### 召回并发与 Memory Island 失败降级

- 文件：`shenyu_gateway/context_builder.py`、`shenyu_gateway/mem_notes/_search.py`、`shenyu_gateway/stars/_activity.py`
- 已确认问题：Mem 或 Stars 普通异常会从主 `gather` 抛出，使已存在的“召回失败保留上一版 island”逻辑无法执行，整次聊天失败。
- 修复：ContextBuilder 分别将 Mem/Stars 普通异常转换为 `ok=false`；对应来源保留上一版 island，其他来源继续使用成功结果。`CancelledError` 不被吞掉。
- 性能：Mem semantic 的 keyword index/vector rows 并行；Stars harmony 的 from/to link 查询并行。
- 语义保持：候选合并、评分、阈值和正文不变；各查询仍独立 fail-soft。
- 暂不并发：island 进入后的 Stars activation 和 Mem triggered 写入，避免在失败场景下改变部分副作用顺序。
- 测试：验证真实并发重叠和双召回故障保留 previous island。
- 验证：召回相关 132 项、全仓 400 项通过。

### 召回重复读取与特征查询

- 文件：`shenyu_gateway/mem_notes/_search.py`、`shenyu_gateway/stars/_activity.py`
- Mem：一次 contextual recall 的 active rows 复用于 running-joke、entity、keyword 和 semantic note hydration；常见 notes 表读取从 2–3 次降为 1 次，缺失候选 ID 才补查。
- Stars：recent fatigue、ACT-R 和 ignored penalties 三类独立特征读取并行。
- 语义保持：公共 `search_notes()` 默认仍独立查询；评分、候选顺序、阈值、反馈和正文不变。
- 未优化：Stars run/candidate 写入会产生 `run_id`、`candidate_id`，同时服务反馈和 activation，不属于可直接后台化的纯日志。
- 测试：验证 contextual 常见路径只有一次 notes 表读取，以及 Stars 三类特征读取实际重叠。
- 验证：召回相关 134 项、全仓 402 项通过。

### OpenAI-compatible 自然 EOF 收尾

- 文件：`shenyu_gateway/stream_proxy.py`
- 行为：上游自然结束且未发送 `data: [DONE]` 时，由网关补发一次 sentinel。
- 不影响：正常已有 `[DONE]` 的上游、Anthropic 转换路径、usage 内容。
- 测试：`tests/test_gateway_streaming.py` 中的普通直通流回归测试。
- 验证：相关协议、流式和工具测试共 149 个通过。

### 双协议 cache usage 保真

- 文件：`shenyu_gateway/upstream_adapter.py`、`shenyu_gateway/tool_loop.py`、`gateway.py`、`admin/src/views/LogsView.vue`
- 已确认问题一：Anthropic usage 转换为 OpenAI-compatible completion 时只保留 cache read，丢失 `cache_creation_input_tokens` 和 `cache_creation` TTL 明细，普通流、非流和工具轮日志均无法诊断缓存写入。
- 修复一：继续提供 `prompt_tokens_details.cached_tokens` 兼容字段，同时保留供应商上报的 cache read、cache write 和 TTL 创建明细；明确上报的 0 也保留。
- 已确认问题二：部分兼容 relay 同时返回 5m/1h 创建 token 分项且不返回总数时，摘要使用 `or` 只取第一项，导致总写入小于明细之和。
- 修复二：优先使用供应商明确总数；缺少总数时对已有 TTL 明细求和。
- 总输入显示：新增每轮 `cache_usage.total_input_tokens`。Anthropic 按未缓存输入 + read + creation 归一化；OpenAI-compatible 直接使用已包含 cached 子集的 `prompt_tokens` / `input_tokens`。前端标签从含输出的 `tok` 改为不含输出的 `input`。
- 单条缓存率：`⚡ cached` 后的百分比使用 read / normalized total input；没有可靠总输入时不显示百分比。原 read / (read + creation) 口径保留为详情中的“前缀复用率”，不再作为紧凑缓存率。
- 边界：没有改变 cache breakpoint、上游 payload、客户端基本 token 字段或费用计算；provider unknown 状态留待日志/API 包统一建模。
- 测试：`tests/test_upstream_adapter_stream.py` 覆盖 Anthropic 原值保留和双 TTL 求和，13 项通过。

### Cache reported/unknown 状态

- 文件：`shenyu_gateway/upstream_adapter.py`、`gateway.py`、`admin/src/api/logs.ts`、`admin/src/views/LogsView.vue`
- 已确认问题：原摘要只有 `hit/write` 布尔值，无法区分供应商明确上报 0 与完全缺少缓存字段；详情页还会在 write > 0、read = 0 时隐藏写入事实。
- 修复：新增可选 `read_reported`、`write_reported`、`reported` presence 字段；多轮聚合保持任一轮上报状态；详情页只在 `reported=true` 时声称供应商上报，否则显示 unknown。
- 旧日志兼容：新字段均为可选；旧日志缺失 presence 时按 unknown 展示，不反推 cache miss。
- 测试：adapter 覆盖 reported zero/unknown，配置测试覆盖 read/write/unknown 三轮聚合；Admin 生产构建通过。

### 工具轮逐轮 cache marker 证据

- 文件：`shenyu_gateway/upstream_client.py`、`shenyu_gateway/tool_loop.py`、`shenyu_gateway/gateway_admin_routes.py`、`admin/src/views/LogsView.vue`
- 已确认问题：工具请求只在顶层日志保存第一轮 `prompt_cache`，后续轮只有 usage 和 payload 摘要；未开启完整 payload 时，无法直接区分“网关后续轮没带长历史断点”和“relay 忽略了该断点”。
- 修复：每个 `internal_tool_rounds[]` 保存独立的 `prompt_cache`，包括 breakpoint 路径、前缀指纹、TTL、tail guard，以及最终出站 payload 中实际存在的 `cache_control_marker_count`。Admin Upstream 与 Raw JSON 都可按轮查看。
- 推荐判断顺序：先核对 marker 数量和路径，再比对指纹，最后解释供应商 read/write；只有结构化证据仍不足时才短期开启完整 payload。
- 隐私边界：逐轮结构证据不含消息正文，可以进入 SQLite 安全历史；完整 Messages、upstream payload、Response、图片和原始 Thinking 仍不持久化。
- 测试：`tests/test_gateway_streaming.py` 覆盖两轮独立证据，`tests/test_gateway_store.py` 覆盖安全持久化和列表 API，Admin smoke 覆盖展开轮次后查看 Upstream；全仓 477 项与 Playwright 13 项通过。

### Admin 配置密钥不回显

- 文件：`shenyu_gateway/config_routes.py`、`admin/src/api/config.ts`、`admin/src/views/ConfigView.vue`
- 已确认问题：`/api/config/full` 和配置更新响应直接返回 gateway、upstream、Hisense、Calendar 与 Supabase 长期密钥明文；上游 preset 还会把 API key 存入浏览器 localStorage。
- 修复：配置响应中的密钥值固定为空，只返回对应 `*_configured` 状态；前端普通保存仅提交用户新输入的非空密钥，留空保持服务端现值；preset 不再读取、写入或切换密钥。
- 本地迁移：加载历史 preset 后立即以无 key 结构重写 localStorage，移除旧版本遗留密钥。
- 保留边界：Admin 更新仍会把密钥写入 `.env` 和 SQLite `config_overrides` 用于容器重建恢复；两处都属于部署敏感资产，必须纳入备份与访问控制。
- 测试：GET/POST 响应不含明文密钥且 configured 状态准确；相关配置、adapter、store 共 55 项通过；Admin 生产构建通过。

### Admin 日志列表重量判断

- 列表 API 只读取内存 deque，硬上限 30 条；不返回完整 messages、response、upstream payload 或 memory island 正文，详情在展开时读取完整对象。
- 列表仍包含每轮摘要、tools、usage、timeline tail 和上下文决策，复杂工具请求可能偏重，但目前没有响应体积或页面性能证据支持破坏现有排障体验。
- 暂不修改列表 schema；后续先采集典型 30 条列表 JSON 大小和渲染耗时，再决定是否拆分二级摘要。

### 工具注册一致性与仓库卫生

- 文件：`tests/test_gateway_tool_registry.py`、`shenyu_gateway/tool_registry.py`、`.gitignore`
- 工具契约：新增动态集合测试，要求每个 gateway schema 都有 handler，且未公开 handler 必须恰好属于隐藏兼容集合；避免未来新增工具只改 schema 或只改执行器。
- 编码：移除 `tool_registry.py` 的 UTF-8 BOM，正文与运行行为不变。
- 临时资产：仓库 `tmp/` 当前约 55 MB，主要为缓存分析 SQLite 和 retained JSON；未删除调查资产，只追加根级 `/tmp/` ignore 规则。
- 测试：工具 registry 51 项通过，Python 编译通过。

### Pending mixed tool transcript 生命周期

- 文件：`shenyu_gateway/store/_pending.py`、`shenyu_gateway/store/_admin.py`、`tests/test_gateway_store.py`、`tests/test_gateway_streaming.py`
- 已确认：通用 `prune_runtime_state()` 不按消息 retention 或 pending 数量删除 active transcript，只删除 `consumed_at` 已设置或 `expires_at` 已过期的记录。
- 查找边界：只匹配同 session、未消费、未过期且 canonical client tool IDs 完全一致的最新记录；同会话存在 30 条其他 pending 时目标仍可找回。
- 测试：新增通用 prune 固定样本，验证 active 保留、consumed/expired 删除；store 21 项通过。

### 长窗口 mixed tool 边界

- 文件：`shenyu_gateway/context_window.py`、`shenyu_gateway/prepare_messages.py`、`tests/test_gateway_trim.py`、`tests/test_gateway_streaming.py`
- 顺序：客户端历史先经过 tool-safe chunked trim；snapshot 保存裁剪后的客户端可见历史；随后 pending 注入恢复原 assistant mixed calls、gateway tool results 和客户端 tool results，形成实际上游序列。
- 已确认：裁剪起点不会停在 assistant tool call 与结果之间；长历史下完整 client continuation 保留，pending 注入后 gateway/client 两类结果仍与原 assistant 调用成组。
- 测试：新增长窗口 + mixed pending 组合样本；gateway streaming 测试通过。

### Mixed gateway/client 部分失败契约

- 文件：`shenyu_gateway/tool_loop.py`、`tests/test_gateway_streaming.py`、`tests/test_upstream_adapter_stream.py`
- 共享边界：OpenAI-compatible 与 Anthropic tool calls 先转换为统一 completion，再进入 mixed tool executor；执行器不依赖供应商协议。
- 成功：gateway result 保存到隐藏 pending transcript，客户端只收到 client calls，正文和 `finish_reason=tool_calls` 不变。
- 失败：gateway tool 返回 `ok=false` 时仍保存失败 result 并记录 tool error，不吞掉 client call，也不把隐藏结果泄漏到响应正文或流式 replay。
- 测试：覆盖 mixed gateway 成功、失败、pending clean copy、流式 replay 去重和 Anthropic mixed text/tool index 转换。

### Cold Start 精确重叠去重

- 文件：`shenyu_gateway/context_window.py`、`shenyu_gateway/prepare_messages.py`、`tests/test_gateway_trim.py`
- 已确认问题：active/manual cold-start bridge 与客户端已回传历史存在相同边界消息时，原逻辑会机械插入并把同一旧轮次发送两次。
- 修复：只删除 bridge 最长后缀与客户端非 system 历史最长前缀之间角色、内容和工具字段完全一致的连续消息；不做模糊文本或非连续去重。
- 观测：新增 `cold_start_bridge_overlap_messages`，实际 bridge 数量按去重后消息计算。
- 测试：覆盖完整双消息重叠、重复模式只消除一次，以及角色变化不去重。

### 默认 request-log 正文最小化

- 文件：`shenyu_gateway/request_logs.py`、`shenyu_gateway/store/_request_log_history.py`、`LOGS_GUIDE.md`、`tests/test_gateway_streaming.py`、`tests/test_gateway_store.py`
- 已确认问题：UI 文案把完整 payload 描述为显式开启，但后端环境变量缺省值实际为 true，最近 30 条日志默认保存完整 prepared messages、upstream payload 和 response。
- 修复：`GATEWAY_LOG_FULL_PAYLOADS` 改为显式 true/yes/on/1 才开启；默认仅保留摘要、预览与计数。
- 边界：完整日志仍只在进程内，重启消失；安全摘要默认在 SQLite 保留最近 200 条并跨容器恢复。临时开启完整日志时 Admin/API credential redaction 继续生效，但完整对话正文、payload、图片和 Thinking/signature 不进入持久历史。

### 持久化正文副本与部署边界

- 文档：`docs/architecture/REQUEST_CONTEXT.md`、`README.md`
- 已完成：按数据产品记录正文范围、默认保留、功能责任和 session 删除边界。
- 部署：默认 SQLite 位于容器 `/app/data`；Dockerfile 无 volume 声明，Coolify 未挂卷时容器替换会丢失 SQLite 与容器内 `.env`，但不会删除 Supabase archive。
- 结论：当前多副本均有不同功能责任，不建议在缺少替代数据源时合并或删除；优先通过 retention、默认日志最小化和明确删除范围控制风险。

### 历史事件与 epoch 契约

- 文件：`shenyu_gateway/context_window.py`、`tests/test_gateway_trim.py`
- 已确认：`retry`、`roll`、`edit_tail`、client tool continuation 和普通 continuation 保持当前 epoch；`branch` 重建 epoch 并标记 `history_branch`。
- `edit_tail` 保持窗口 anchor，但作为新的人类输入重新执行召回；`retry/roll/continuation` 可复用 previous island。
- 测试：增加事件分类表和 epoch 参数化矩阵，覆盖尾部编辑、缩短历史、旧历史分支和工具续接。

### SQLite override 来源可见性

- 文件：`gateway.py`、`shenyu_gateway/config_routes.py`、`admin/src/api/config.ts`、`admin/src/views/ConfigView.vue`
- 行为：Admin 保存的配置仍持久化到 SQLite 并在启动时恢复；页面不再把这些正常持久化项渲染成“覆盖部署配置”的告警清单。
- 安全：不返回 override 值；运行时通过 Admin 保存的新键会同步进入提示集合。
- 测试：配置 API 来源与密钥不回显测试通过，Admin 生产构建通过。

### 复合 credential 键脱敏

- 文件：`shenyu_gateway/gateway_admin_routes.py`、`tests/test_gateway_store.py`
- 行为：除标准键名外，递归 redaction 还覆盖 `*_api_key`、`*_auth_token`、`*_access_token`、`*_client_secret`、`*_webhook_secret`、`*_private_key` 和 `*_password`。
- 保留：`token_count`、`max_tokens` 等统计/协议字段不因包含 token 字样而被误删。
- 测试：嵌套 extra body/tool args、URL query、复合 secret 键和普通统计字段均有固定样本。

### Memory Island 主召回失败边界

- 文件：`shenyu_gateway/context_builder.py`、`shenyu_gateway/mem_notes/_search.py`、`shenyu_gateway/stars/_recall.py`
- 已确认：Mem active-row 主查询和 Stars candidate 主查询异常不会被内部伪装成 `ok=true/items=[]`，而是到 builder 统一转换为 `ok=false` 并保留对应 previous island。
- 辅助降级：Mem semantic、Stars harmony、ACT-R、ignored 和 fatigue 等辅助通道可在失败时返回空特征；这会降低排序质量，但不会把整个来源误判成成功空召回。
- 后续：辅助通道需要 failure flags/trace 提升可观察性，暂不因诊断需求改变当前 fail-soft 评分语义。

这项修改在分区总审之前完成，保持独立，不作为继续零散修改的先例。
