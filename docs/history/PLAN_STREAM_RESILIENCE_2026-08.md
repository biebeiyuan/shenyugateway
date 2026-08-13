# 交接文档：PWA 后台断流不丢回复 + 流健康看门狗（2026-08）

> 本文档给新线程直接执行用。方案已经用户批准；**服务端部分已改完（见"已完成"）不要重做**，剩余为 PWA 部分与测试验证。
> 原始批准方案存于 `C:\Users\曾\.claude\plans\toasty-strolling-hare.md`（Windows 侧），内容已并入本文。

## 1. 背景与目标

安卓 PWA 切后台/锁屏时，进行中的 SSE 流式回复有两种死法：

1. **连接被掐**：网关检测到客户端断开后丢弃上游正在生成的回复——不写会话历史、不写快照。回前台后回复找不回（用户已实际遇到）。
2. **socket 静默死亡**（Doze + NAT 过期）：PWA `reader.read()` 永远挂起，UI 卡死在"正在看着这边…"，输入框锁死。

目标：**发完消息可以放心切后台，回来时答案在那里**。方案 = 服务端"断了也照常读完并落库" + 客户端"死链自愈 + 回前台自动补拉"。

用户已定参数：客户端看门狗 **180 秒**；服务端 keepalive **15 秒**（入口走 Cloudflare Tunnel，约 100s 无数据会掐连接）。

## 2. 方案总览（6 项）

| # | 改动 | 层 | 状态 |
|---|------|----|------|
| 1 | `resilient_sse_response` 可分离 SSE 包装器：断连后后台读完上游、照常落库 + 15s keepalive | 服务端 | **已完成** |
| 2 | `_on_stream_complete` 断连兜底：非 ok 且有文本仍写会话 | 服务端 | **已完成** |
| 3 | 客户端 180s 停滞看门狗 + `[DONE]` 截断识别 | PWA | 待做 |
| 4 | 回前台/重启时尾部对账 reconcile | PWA | 待做 |
| 5 | 流式期间节流落盘 + pagehide 强制落盘 | PWA | 待做 |
| 6 | visibilitychange 版本检查（节流）+ onUnmounted abort | PWA | 待做 |
| — | 服务端单测 + vitest + 全量回归 | 测试 | 待做（含真机验收） |

## 3. 已完成的服务端改动（新线程勿重做，只需验证）

### 3.1 `shenyu_gateway/streaming.py`

- 顶部 import 增加了 `Callable`（typing）和 `logger`（`from .runtime import logger`）。
- 新增 `resilient_sse_response(inner_gen, *, model, keepalive_interval=15.0, on_client_disconnect=None)`（约 174 行 `_sse_response` 之后）：
  - producer task 把 `inner_gen` 的事件灌入无界 `asyncio.Queue`，结尾放 `_QUEUE_END` 哨兵；非取消异常记入 `producer_error` 列表由消费侧 re-raise。
  - 消费生成器 `asyncio.wait_for(queue.get(), keepalive_interval)`，超时 yield `_stream_keepalive_event(model)`。
  - 消费侧捕获 `(asyncio.CancelledError, GeneratorExit)`（客户端断开）→ `_detach_producer()`：不取消 producer，把它放进模块级强引用集合 `_DETACHED_STREAM_TASKS`（防 GC），调 `on_client_disconnect()`，另起 watchdog task 在 `_DETACHED_DRAIN_MAX_SECONDS = 30*60` 秒后仍未完成才 `producer.cancel()`，然后 re-raise。
  - 效果：断连后 producer 把 `stream_proxy.generate()` 迭代到自然结束，其 `finally` 里的 `on_complete(terminal_status="ok", ...)` 照常触发 → 正常落库。
- `read_next_stream_chunk` 的 `request` 参数改为可选（默认 `None`）；为 `None` 时跳过 `is_disconnected()` 检查（配合包装器，断连不再是终止条件）。旧签名调用（显式传 request）行为不变。
- 旧 `_sse_response` 保留未动（测试还在用）。

### 3.2 `shenyu_gateway/stream_proxy.py`

- import 改为 `resilient_sse_response`（去掉 `_sse_response`）。
- `stream_chat()` 签名新增 kwarg `on_client_disconnect: Optional[Callable[[], None]] = None`。
- 两处返回（openai 路径、anthropic 路径，原 288/487 行）改为 `return resilient_sse_response(generate(), model=model, on_client_disconnect=on_client_disconnect)`。
- `generate()` 内部逻辑未动：其 `except asyncio.CancelledError` 分支在新机制下基本不可达（只有 30 分钟 watchdog 取消时触发），保留作兜底。

### 3.3 `gateway.py`

- `_stream_chat()`（约 602 行）签名新增 `on_client_disconnect: callable = None` 并透传给 `stream_proxy.stream_chat`。

### 3.4 `shenyu_gateway/chat_pipeline.py`

- import 改为 `resilient_sse_response`。
- 工具环流式路径（`_run_gateway_tool_path`，原 384 行）：定义 `_note_client_disconnected()`（置 `log_entry["client_disconnected"] = True`），`return resilient_sse_response(_tool_loop_stream(), model=body.model, on_client_disconnect=_note_client_disconnected)`。
- 纯代理路径（`_run_plain_upstream_path`，现约 454-549 行）：同样定义 `_note_client_disconnected` 并作为 `on_client_disconnect` 传给 `self.stream_chat(...)`。
- `_on_stream_complete` 非 ok 早退分支（现约 473-485 行）：`terminal_status == "client_disconnected"` 且 `collected_text or echo_content` 非空时，return 前调 `sessions.log_assistant_output(session_id, {"role": "assistant", "content": collected_text}, echo=echo_content)`。不写 snapshot、不 mark_context_consumed（内容不完整）。仅 watchdog 取消时会走到。

### 3.5 `shenyu_gateway/tool_loop.py`

- `run_internal_tool_loop_stream` 主循环（约 592 行）：`read_next_stream_chunk(..., request=None)`（原为 `ctx.request`）；`disconnected` 分支从 `return` 改为记 `ctx.log_entry["client_disconnected"] = True` 后 `continue`（该分支在 request=None 下实际不再返回 disconnected，属防御性保留）。
- 工具执行后的检查（原约 779-783 行）：`if await ctx.request.is_disconnected()` 从"置 status + return"改为只记 `ctx.log_entry["client_disconnected"] = True`，不再中断循环。

### 3.6 验证状态

**尚未跑任何验证**：`python3 -m py_compile` 被沙箱临时拦了两次没执行成功，pytest 也没跑。新线程第一步就该跑（见 §6）。

已知需要关注的现有测试（`tests/test_gateway_streaming.py`）：

- `test_read_next_stream_chunk_closes_upstream_when_client_disconnects`（2410 行）：显式传 `request=`，应仍通过。
- 若有测试断言"tool loop 断连即终止 / status=client_disconnected"，行为已变，需要按新语义改断言（断连后继续跑完、只记 `client_disconnected` 标记）。
- `test_sse_response_disables_proxy_buffering`（1727 行）用旧 `_sse_response`，不受影响。

## 4. 待做：PWA 改动（任务 #16-#18）

### 4.1 `pwa/src/stream/sse.ts` — 看门狗 + sawDone（任务 #16）

现状（120-143 行）：`pumpSseStream(body, onFrame, onChunkEnd)` 的 `reader.read()` 无超时；EOF 即结束，不要求 `[DONE]`（静默截断无法识别）。`parseSseFrame` 返回 true 表示收到 `[DONE]`。

改动：

- 签名改为 `pumpSseStream(body, onFrame, onChunkEnd?, stallTimeoutMs?)`，返回 `Promise<{ sawDone: boolean }>`。
- 每次 `reader.read()` 与 `stallTimeoutMs` 定时器 race；超时则 `reader.cancel()` 并 `throw new Error('连接停滞，可能已断开')`。注意每轮 read 后清掉定时器防泄漏。
- `sawDone`：任一 `onFrame(frame)` 返回 true 即置 true。
- `pwa/src/types.ts` `UiMessage` 加 `truncated?: boolean`。
- `App.vue` `sendConversation`（约 900-991 行）调用处传 `180_000`；流结束后 `!sawDone` → 给 assistant 置 `truncated = true`、`errorNotice` 提示"回复可能被截断，正在尝试找回…"，触发 reconcile（§4.2）。看门狗抛错走现有 catch（置 `assistant.error`）后同样触发 reconcile。
- 检查 `pwa/src/session/persistence.ts` 序列化是否透传新字段（大概率零改动，确认即可）。

### 4.2 `App.vue` — `reconcileTailFromServer()`（任务 #17）

利用现有 `fetchSessionDetail(clientContext(), sessionTag.value, limit)`（`api/client.ts` 81-87 行）+ `sessionHistoryRows` / `sessionMessageParts` / `hydrateToolEvents`（`openSession` 481-520 行是现成参照）。

逻辑：取 `recent_messages` 最后一条 assistant 行——

- 本地最后一条是 user（无回复）→ 把服务器 assistant 行按 openSession 的映射转成 UiMessage 追加，并对该行 `hydrateToolEvents`。
- 本地最后一条 assistant 带 `error`/`truncated`，且服务器同轮文本更长 → 替换其 content/echo，清 error/truncated。
- 都不满足 → 无操作。**不做整体替换**（openSession 的整体替换对 attachments/thinking 有损，仅用于切会话）。

触发点：

1. `visibilitychange` → visible 且 `!busy` 且末轮不完整（最后一条是 user，或 assistant 带 error/truncated）；
2. 看门狗/网络错误 catch 后；
3. `onMounted` 恢复本地消息后（覆盖进程被杀重启场景）。

服务端 drain 可能未跑完 → 找不到时按 5s/15s/30s 退避重试，期间 `status` 显示"正在找回后台期间的回复…"；找回后 `persistMessages()`。

### 4.3 `App.vue` — 节流落盘 + 小修（任务 #18）

- `pumpSseStream` 的 `onChunkEnd`（现在只 `scrollToBottom`）加节流 `persistMessages()`（约 3 秒一次）。
- 注册 `pagehide` + `visibilitychange→hidden`：同步调 `persistMessages()`（localStorage 同步 API，切后台瞬间能写完）。
- `visibilitychange→visible` 且 `!busy`：调 `checkPwaBuildInfo()`，节流 ≥5 分钟一次（busy 时跳过，避免 `main.ts` 的 `controllerchange` reload 杀掉活动流）。现状 `checkPwaBuildInfo` 只在 `openSettings`（718-721 行）触发。
- `onUnmounted` 里 `activeController?.abort()`（现状不 abort）。

## 5. 待做：测试（任务 #19）

服务端（`tests/test_gateway_streaming.py` 内或旁边新增）：

1. `resilient_sse_response`：消费者中途取消（模拟断连）→ 断言 producer 跑完、`on_complete` 收到完整文本且 `terminal_status=="ok"`、`on_client_disconnect` 被调用。
2. keepalive：注入慢 producer，断言超时间隔产出 keepalive 事件。
3. `read_next_stream_chunk(request=None)`：上游 pending 时返回 keepalive 而非 disconnected。
4. tool_loop：断连标记后循环继续跑完并正常收尾（改/补现有断连用例）。

PWA（vitest，`pwa/tests/sse.spec.ts` 扩展 + 新 spec）：

1. `pumpSseStream` 停滞超时抛错；EOF 无 `[DONE]` → `sawDone=false`；正常流 `sawDone=true`。
2. reconcile 三分支：追加 / 替换 / 无操作。

全量回归：

```bash
# WSL: /home/yuan/shenyu-gateway
python3 -m py_compile shenyu_gateway/streaming.py shenyu_gateway/stream_proxy.py shenyu_gateway/chat_pipeline.py shenyu_gateway/tool_loop.py gateway.py
pytest tests/
cd pwa && npm test && npm run build
```

## 6. 验收标准

代码层：上述全部测试通过、`npm run build` 通过。

**安卓真机实测**（`docs/frontend/STYLE_AND_CRAFT.md` 验收铁律，桌面浏览器不作数）：

1. 发长回复 → 立即切后台 ≥2 分钟 → 回前台：回复完整出现（流仍活或 reconcile 补回）。
2. 发消息后锁屏 5 分钟（触发 NAT 过期）→ 回来：看门狗已解锁 UI，回复被找回。
3. 流式中途从最近任务杀掉 PWA → 重开：用户消息与半截/完整回复都在（节流落盘 + reconcile）。
4. 正常长思考（>100s 无输出）不再被 Cloudflare 掐断（15s keepalive 生效）。
5. 服务端日志确认：断连场景 request log 带 `client_disconnected: true` 且最终 `status: ok`，会话历史有完整 assistant 行。
