# 日志页小指南

这份说明是给“过一阵忘了每个框是什么意思”的时候看的。日志页优先按真实链路展示，不替上游猜测计费或审核逻辑。

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
- **Response**：看这一轮模型实际返回的正文。粉色框里是调用工具前的正文，绿色框里是最终正文。
- **Upstream**：看这一轮完整上游 payload；只在需要核对协议、工具或缓存断点时打开。
- **Meta / Raw JSON**：工程排障备用，平时可以不看。

默认只保留摘要、预览和计数，不在 request log 中保存完整 Messages、Upstream payload 或 Response。需要短期排查协议问题时，可以显式设置 `GATEWAY_LOG_FULL_PAYLOADS=true`；这些完整内容只存在于进程内最近 30 条日志，重启即消失，但仍可能包含敏感对话，排查结束后应关闭。

## 小岛与缓存

- 小岛显示的是**实际渲染并发送给模型**的星星和 Mem，不是候选列表。
- 小岛重写可能改变缓存前缀，但是否影响计费仍取决于供应商的缓存实现。
- `tail_guard_user_turns` 表示第四个断点主动避开的最近 user turn 数：普通纯文本为 `0`，存在设备状态附件时通常为 `3`，仅有图片时为 `2`。这些最近消息仍会完整发给模型，只是不放进稳定尾部缓存前缀。
- 页面只显示供应商原样返回的 `cached/input/output/write` 数值，不再计算缓存率，也不据此承诺省了多少钱。
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
```

公网日志 API 正常时也可以去掉 `--via-ssh`；SSH 仍是 Cloudflare 或公网入口异常时的可靠备用路径。
