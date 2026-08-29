# Shenyu Gateway：从这里开始

这是给人和新开的 coding agent 共用的懒人入口。先读这一页，再按任务跳转；不需要把仓库里的 Markdown 全部读完。

> 先按任务选入口，不必逐张读地图：`README.md` 回答“文件在哪里”；`SYSTEM_ZONES.md` 回答“谁负责、跨区要看什么”；`DOCS_MAP.md` 回答“哪份文档仍然现行”；`STYLE_AND_CRAFT.md` 回答“前端从哪里改、怎样验证”；Admin《家里地图》把同一批权威事实整理给圆圆（Owner）看，不作为 Agent 的主要入口。

## 先记住四件事

1. Shenyu Gateway 接收 OpenAI-compatible 请求，但上游既可以是 OpenAI-compatible，也可以是 Anthropic；协议差异应留在 provider adapter，不能把某个 relay 的行为写成全局规则。
2. 请求正文会经过上下文整理、Memory Island 注入和工具路由，再发送给上游。日志里的原始窗口、上下文快照和实际上游消息是三个不同阶段，不是简单的重复副本。
3. 工具有“网关执行”和“客户端执行”两类。同一轮可以同时出现两类工具，因此存在 mixed tool 和 pending transcript 机制。
4. 这是生产项目，而且 **`master` 分支就是那个生产**——Coolify 盯着它自动部署，推上去就是上线到沈予和圆圆正在住的网关。先看证据和测试，再做最小修改；不要根据猜测重构请求、流式、工具或记忆链路。推 master 前的验证基线在 `docs/DELIVERY.md`。

## 我现在想做什么？

| 任务 | 先读 | 然后读 |
|---|---|---|
| 快速认识项目和文件放在哪里 | `README.md` | `docs/architecture/SYSTEM_ZONES.md` |
| 查一次请求到底怎样走 | `docs/architecture/REQUEST_CONTEXT.md` | `DEBUGGING_GUIDE.md` § Chat Request Flow |
| 查工具、mixed tool 或 pending transcript | 本页 § 工具人话解释 | `docs/architecture/REQUEST_CONTEXT.md` § Tool Calls |
| 查 Memory Island、裁剪、cold start | `docs/architecture/REQUEST_CONTEXT.md` | `docs/architecture/AUDIT_MATRIX.md` § 区域五：上下文窗口与 Memory Island |
| 查 Mem、Stars、Room、来历书/共享书架（旧内部名：矛盾书） | `docs/architecture/SYSTEM_ZONES.md` § 住户数据注意事项 | 按对象读 `docs/architecture/MEMORY_ROOM.md` 或 `docs/architecture/REQUEST_CONTEXT.md`；改核心语义再读 `DESIGN.md` |
| 新增或部署 Supabase 表、索引、RPC | `docs/architecture/REQUEST_CONTEXT.md` § Supabase Long-Term State | 对应 `supabase/migrations/*.sql`；先应用迁移，再部署依赖它的代码并做 API/页面验证 |
| 查 OpenAI/Anthropic、缓存或 usage | `docs/architecture/REQUEST_CONTEXT.md` | `docs/architecture/AUDIT_MATRIX.md` § 区域三：上游协议与供应商适配 |
| 线上报错、流卡住、工具没执行 | `DEBUGGING_GUIDE.md` | `LOGS_GUIDE.md` |
| 看已经确认的问题和暂不该动的地方 | `docs/architecture/AUDIT_MATRIX.md` | 对应测试和代码 |
| 判断某份 Markdown 是否仍然有效 | `DOCS_MAP.md` | 对应现行专题文档 |
| 修改代码 | `AGENTS.md` | 本表对应的专题文档 |
| 改 PWA 前端（聊天界面、流式、会话交接） | `README.md` § PWA chat frontend | `docs/frontend/STYLE_AND_CRAFT.md` § 五的 PWA 行；涉及请求、流式或会话契约时再读 `docs/architecture/REQUEST_CONTEXT.md` § External Frontend Contracts |
| 改 admin 前端（配色、组件、动效、演示预览） | `docs/frontend/STYLE_AND_CRAFT.md` | `admin/src/theme/tokens.css`、`admin/src/demo/` |

## 工具人话解释

### Gateway tool

网关自己会执行的工具，例如读取心跳、搜索记忆、手写日历手记（`shenyu_add_calendar`）或访问 Supabase 数据。模型发出调用后，Shenyu Gateway 执行它，把结果送回模型，再让模型继续回答。

普通线程默认使用一个节省提示词的入口 `shenyu_gateway_tool`。它像总机：参数中的 `tool` 指定真正要调用的 `shenyu_*` 或 `supabase_*` 工具，`params` 放参数。

### Client tool

由聊天客户端提供和执行的工具，例如客户端自己的读文件、访问网页或其他本地能力。网关可以把定义传给模型，也会转发模型生成的调用，但不会冒充客户端执行它。

项目里支持 client tool，不代表每个客户端一定提供相同工具。实际有哪些，以当前请求携带的 tool schemas 和客户端配置为准。

### Mixed gateway/client tool

模型在同一条 assistant 消息里同时请求 gateway tool 和 client tool，就是 mixed tool：

```text
assistant 同时请求：
  - 网关查记忆
  - 客户端读文件
```

网关能立即完成第一项，但第二项必须返回客户端执行。两类调用不能互相吞掉，也不能把网关内部结果伪装成客户端结果。

### Pending transcript

这是 mixed tool 的临时“存根”。网关先把原始 assistant 工具调用和已经完成的 gateway result 暂存；客户端下一次带回 client tool result 时，网关再把完整工具对话拼回去发给上游。

没有它，上游下一轮可能只看到客户端结果，却看不到同轮的网关调用和结果，工具协议会断裂。它不是新的用户工具，也不是长期记忆；记录消费后删除，未消费记录有过期时间。

### Compatibility wrapper / broker

这里的 wrapper 或 broker 不是另一个供应商，也不是偷偷改变工具行为。它是兼容和省 token 的薄入口：

- `full` 模式直接暴露每个 gateway tool 的独立 schema；
- `broker` 模式只暴露 `shenyu_gateway_tool`，再由它分派到同一批 handler；
- 老参数 `arguments` 仍可兼容，新调用使用 `params`；
- 隐藏兼容工具只服务旧调用，不应被当成公开产品能力。

“兼容”应保持在边界层，不能把某个客户端、Anthropic、OpenAI-compatible relay 的特殊字段扩散到全系统。

## Debug 文档是不是都必须读？

不是。

- `DEBUGGING_GUIDE.md` 是故障手册：线上异常、流式卡住、relay 报错、工具未执行时再读。
- `LOGS_GUIDE.md` 是日志页面说明书：忘记颜色、轮次、小岛或缓存字段含义时再读。
- 平时开发只需从本页跳到对应专题；新线程不需要预读两份 Debug 文档全文。

这两份文档仍有必要保留，因为架构说明回答“系统怎样设计”，排障手册回答“坏了先查什么”，日志指南回答“页面上的证据是什么意思”。三者职责不同。

## Windows 搬到 WSL 后的工作方式

仓库现在以 WSL/Linux 为主要开发环境。历史文件可能仍带 CRLF 或混合换行，这通常只会制造 diff 噪音，不等于业务代码损坏。

- 在 `/home/yuan/shenyu-gateway` 内使用 Linux 工具、Python、Node 和 Docker。
- `.gitattributes` 规定文本文件使用 LF；只在实际编辑文件时自然归一化，不做全仓换行重写。
- 中文文件按 UTF-8 处理，优先用 `apply_patch` 修改。
- 不提交 `node_modules/`、构建产物、临时日志、token、SSH key 或本地 debug 配置。
- 看到整文件都变化时，先检查换行和编码，不要立刻接受巨大 diff。
- Python 文件修改后运行 `python -m py_compile`；中文修改后扫描 `淇|閺|鈹|銆|锛|紝|娌堜簣`。

这些规则已写入 `.gitattributes`、`.gitignore` 和 `AGENTS.md`。当前不建议为了“看起来统一”批量重写历史文件；那会让真实业务修改更难审查。

## 新线程最短提示词

可以只告诉新线程：

> 先读 `AGENTS.md` 和 `START_HERE.md`，按入口找到本任务相关的现行文档；先检查 `git status`，不要覆盖已有修改。涉及线上异常先看日志，涉及请求、工具、上下文、缓存或记忆时先确认完整链路和跨区边界，再做最小修改。

文档状态、历史设计稿和现行事实的完整索引见 `DOCS_MAP.md`。
