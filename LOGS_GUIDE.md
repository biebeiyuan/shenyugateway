# 日志页小指南

这份说明是给“过一阵忘了每个框是什么意思”的时候看的。日志页优先按真实链路展示，不替上游猜测计费或审核逻辑。

## 工具报错页

“工具报错”是独立于普通请求日志的专表视图。网关工具返回 `ok: false` 时，工具循环会把目标工具、参数、错误文本和分类写入 SQLite `tool_error_log`，前端通过 `GET /api/gateway/tool-errors` 读取。因此普通请求可能整体成功、请求日志里没有红色错误，但这里仍有一条工具失败记录。

- **调用被拒**（`validation`）：参数、工具名或调用契约不符合要求；也可能是底层服务返回了可解释的输入错误。
- **真报错**（`exception` / `config`）：工具已经进入执行后抛出异常，或运行配置缺失，通常需要检查代码、依赖或部署配置。
- 展开记录时先看 `target_tool`，再并排看 `args_json` 和 `error_text`。`shenyu_gateway_tool` 只是总机，真正坏在哪个工具由 `target_tool` 判断。

排障时不要用 `scripts/vps_gateway_logs.py api --errors` 代替这张表；该参数筛选的是请求级错误。完整代码链路和接口位置见 `DEBUGGING_GUIDE.md` § Gateway tool error log chain。

## 先看大框颜色

- **绿色大框**：这次客户端请求的最后一轮上游回复。普通对话通常只有这一框。
- **粉色大框**：工具调用前的中间上游请求。它本身也是一次完整请求，有自己的 Response、Messages、Upstream、缓存 usage 和耗时。
- 多轮之间的连接文字表示：网关执行了工具，再带着 `tool_result` 发起下一轮。
- 红色边框表示请求或该链路出错；先看 Response，再用日志 helper 拉完整错误。

## 每个标签看什么

- **概览**：看记忆小岛是否变化，以及本次真正发送给模型的星星和 Mem 文本。
- **工具执行**：看这一轮实际做了什么、是否成功、用了多久。工具“被提供”不等于模型真的调用。
- **Messages**：看这一轮实际发送给上游的消息序列。后续轮会比前一轮多出 assistant tool call 和 tool result。
- **System**：看本次客户端请求共享的系统上下文。
- **Response**：看这一轮模型实际返回的正文。粉色框里是调用工具前的正文，绿色框里是最终正文。请求出错时，`HTTP NNN` 是实际状态码；`原因（原文）` 直接取自返回 JSON 的 `error.message`、顶层 `message` 等原始字段，下面的 `原始返回` 保留原错误正文。它们不是网关根据关键词统计或自行归类出的结论；无法解析结构时会直接显示原文。
- **Upstream**：默认看这一轮不含正文的 payload 摘要和缓存结构证据；临时开启完整 payload 保留后，才显示实际上游 payload。只在需要核对协议、工具或缓存断点时打开。
- **Meta / Raw JSON**：工程排障备用。Raw JSON 是原始日志对象，不等于实际发给上游的请求 JSON；没有开启完整 payload 保留时，它只含预览、摘要和结构化证据。

日志分两层保留：当前进程内有最近 30 条可继续更新的实时日志；SQLite 默认保留最近 200 条安全摘要（由 `GATEWAY_REQUEST_LOG_RETENTION` 调整），所以挂载数据库持久卷后，更新容器不会再清空前端最近日志。普通结构化诊断字段会随安全 JSON 摘要自动保存；完整 Messages、Upstream payload、Response、图片、原始 Thinking 和 signature 会被统一剔除。摘要里的消息预览最多保留**最新** 100 条、每条正文最多 500 字；超出时日志页 Messages 标签会标明省略了更早的多少条（2026-07-26 之前的旧记录是反方向保留最早 100 条，页面也会说明）。

工具链的每个上游轮次都会单独保存 `prompt_cache` 结构证据：断点路径、前缀指纹、TTL、tail guard，以及最终 payload 中实际存在的 `cache_control` 数量。它们不含消息正文，可以随 SQLite 安全摘要保留；结合该轮的缓存 read/write，可以判断网关是否发出断点以及上游是否兑现。

需要看完整请求内容时，在 Admin 配置页打开「请求日志 → 保留完整请求内容」（等价于环境变量 `GATEWAY_LOG_FULL_PAYLOADS=true`，开关会随配置覆盖持久化，无需重启，只对之后的新请求生效）。完整内容仍只存在于当前进程最近 30 条日志，重启后旧记录会退回摘要和预览；它们可能包含敏感对话，看完建议关闭。

## Anthropic Thinking 标签

工具中间轮的 Response 标题可能显示：

- `Thinking 已保留 N 块`：网关收到了 Anthropic 原生 Thinking 或 redacted Thinking 内容块，并只为尚未结束的工具续轮临时保留。
- `signature ✓`：返回内容里带有不可读的签名字段，续轮时按原样交还上游。
- `redacted ✓`：返回内容里包含 Anthropic 已隐藏的 Thinking 块。

这些标签不是可阅读的 raw 思维链，也不表示网关能够解码隐藏内容。日志只保存块数量和真假标记；即使临时开启完整 payload，Thinking、signature 和 redacted 内容也会被脱敏。

没有显示“Thinking 已保留”也不等于请求没有开启 Thinking。先去 Upstream 摘要查看发出的 `thinking`；如果还要核对这一轮的实际 `output_config.effort`，需临时开启 `GATEWAY_LOG_FULL_PAYLOADS=true` 后查看完整 Upstream payload。然后再判断上游是否真的返回了可续接的原生内容块。

## 小岛与缓存

- 小岛显示的是**实际渲染并发送给模型**的星星和 Mem，不是候选列表。Stars 和 Mem 会用同一套卡片分别展示当前内容、新增、更新和移除；更新显示为“原来 → 更新后”。这份短文本小岛摘要随 SQLite 安全日志历史保留，不要求开启完整 Messages/Upstream payload；完整渲染文本仍遵守进程内临时保留规则。
- 换岛原因会区分正常重合门、历史分支、消息高水位、旧星失效，以及按 star ID、独特原句或“回忆意图 + 唯一候选”的直接点名。直接点名日志只保存类别和计数，不新增保存命中的原句。
- 小岛重写可能改变缓存前缀，但是否影响计费仍取决于供应商的缓存实现。
- `tail_guard_user_turns` 表示第四个断点主动避开的最近 user turn 数：普通纯文本为 `0`，存在设备状态附件时通常为 `3`，仅有图片时为 `2`。这些最近消息仍会完整发给模型，只是不放进稳定尾部缓存前缀。
- 每轮顶部的 `input` 是该次上游请求的总输入，不含输出：Anthropic 使用未缓存输入 + 缓存读取 + 缓存新写；OpenAI-compatible 使用供应商上报的 `prompt_tokens` / `input_tokens`，因为其中的 cached tokens 已是子集，不能重复相加。
- 页面保留供应商原样返回的 `cached/input/output/write` 数值；`⚡ cached` 后的百分比使用 `缓存读取 ÷ 总输入`，表示这一轮有多少输入由缓存读取覆盖。总输入分母不可靠时只显示 cached token 数，不显示百分比。`读取 ÷（读取 + 新写入）` 仍作为单独标注的“前缀复用率”保留在详情中；两者都不是跨请求命中率或账单节省比例。
- 不同供应商、控制台和 API usage 的口径可能不同；需要对账时按 request id 和每一轮分别比较。

## 来源指纹

新请求会比较：

1. 网关上次保存的 assistant 输出；
2. 客户端下一次回传的最后一条 assistant 历史。

结果位于 `client_message_window.assistant_lineage`：

- `match: true`：客户端回传内容与网关保存输出一致。
- `match: false`：响应离开网关后，客户端或中间保存层回传了不同内容。
- `available: false`：缺少可比较的上一条 assistant。

这里只记录 SHA-256 前缀和字符数，不额外保存正文，也不检测任何固定异常字符串。

## 出问题时怎么叫 Codex 看

优先告诉 Codex：

- 大概时间，最好精确到分钟；
- 会话标签；
- 是一直“正在连接 AI”、空回、断流，还是工具后卡住；
- 如果能看到日志，给出日志 ID 或 request ID。

常用命令：

```bash
python scripts/vps_gateway_logs.py api --via-ssh --errors --detail
python scripts/vps_gateway_logs.py api --via-ssh --id <log-id> --detail
python scripts/vps_gateway_logs.py cache --session <session-tag> --limit 20
python scripts/vps_gateway_logs.py cache --session <session-tag> --limit 200
```

公网日志 API 正常时也可以去掉 `--via-ssh`；SSH 仍是 Cloudflare 或公网入口异常时的可靠备用路径。
