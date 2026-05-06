# Shenyu Gateway

Shenyu Gateway 是一个**单入口 provider 网关**。  
Operit 只需要连接它一个入口；Claude 看到的所有能力，都由这个网关统一注入和路由。

它的目标不是做 persona，也不是做 RP。  
它做的是：

- 自动组装上下文
- 维护会话工作层
- 负责正文浮现
- 负责事件记忆补充
- 负责工具路由
- 负责把 Claude 的 tool call 再送回去

---

## 1. 核心原则

1. **一个入口**
   - Operit 只连 `shenyu-gateway`
   - 不从客户端侧拆成多个 provider

2. **Claude 保持主导权**
   - Claude 可以直接读写所有表
   - Claude 自己决定查哪张表、写哪张表、填哪些字段

3. **网关做辅助编排**
   - 自动加简报
   - 自动浮现正文
   - 自动压缩会话
   - 自动做缓存
   - 自动记录“看过什么、浮现了什么”

4. **正文优先于记忆**
   - 当前对话正文优先级最高
   - `room / diary` 优先于 `message_board`
   - `letter / paper` 次之
   - `daily_notes` 轻量补充
   - `memories` 只做事件补充

---

## 2. 总体架构

```text
Operit
  ↓
Shenyu Gateway  (唯一 provider)
  ├─ Context Builder
  ├─ Session / Cache Store (SQLite)
  ├─ Surface Engine
  ├─ Memory Helper
  ├─ Tool Router
  └─ Upstream Adapter (Anthropic / OpenAI)
  ↓
Claude / Upstream Model
  ↓
Tools executed back through gateway
```

---

## 3. 职责分工

### 3.1 Operit 负责什么

- 聊天 UI
- 把消息发给网关
- 展示流式输出
- 展示工具调用过程
- 管理客户端自身的 MCP / workflow / 本地模型能力

### 3.2 Gateway 负责什么

- 统一 provider 入口
- 自动注入 system/context
- 维护 session / summary / frozen window
- 做正文浮现
- 做 memory 补充
- 维护本地 SQLite 工作层
- 统一暴露工具 schema
- 统一处理 tool call 回环

### 3.3 Supabase 负责什么

长期事实源。主要放：

- `memories`
- `journal`
- `room`
- `daily_notes`
- `message_board`
- `heartbeats`
- `meta_summaries`
- `system_docs`
- `memory_tags`
- `memory_links`

### 3.4 SQLite 负责什么

网关工作层，只放运行态和会话痕迹：

- `gateway_sessions`
- `gateway_messages`
- `conversation_summaries`
- `frozen_windows`
- `surface_events`
- `cache_entries`
- `heartbeat_entries`

SQLite 只保存网关运行态，不是长期事实源。真正需要长期保留、跨设备同步、可检索的事实仍应写入 Supabase。

线程区分依赖请求头传入的 `session_tag`：

- 优先读取 `X-Shenyu-Session-Tag`
- 其次读取 `X-Session-Tag`
- 都没有时使用 `default`

因此如果客户端没有给不同聊天线程传不同 header，多条聊天会被归入同一个 `default` session。

---

## 4. 代码入口

当前主逻辑集中在：

- [`gateway.py`](./gateway.py)
- [`.env.example`](./.env.example)
- [`admin/`](./admin)（管理页 / 调试页 / 前端壳）

当前项目还没拆成多文件模块，所以 `gateway.py` 里同时包含：

- 配置加载
- Supabase 客户端
- SQLite 工作层
- 会话管理
- 正文浮现
- 记忆补充
- 工具注册
- 上游协议适配
- API 路由

后续如果要重构，建议按下面方向拆：

```text
gateway.py
  ├─ config / env
  ├─ supabase client
  ├─ sqlite store
  ├─ session manager
  ├─ context builder
  ├─ surface engine
  ├─ memory service
  ├─ tool registry
  ├─ upstream adapter
  └─ API routes
```

---

## 5. 上下文层设计

### BP1: Stable Charter

最稳定的前缀，基本不变。内容包括：

- 不是人格文档
- 不做 RP
- 正常聊天上下文优先
- 正文比 memory 更重要
- Claude 可以直接操作所有表
- 网关工具只是辅助
- `memories` 是事件补充库
- `daily_notes / journal / room / memories` 的用途区别

### BP2: Daily Briefing

新线程第一条消息时注入。判断方式：**请求里非 system 消息只有1条**，视为新对话。
不依赖 session 持久化状态，所以 Operit 每次新建对话都会注入。

简报由 `build_briefing()` 生成，分6个部分：

```text
# 简报

身份锚（固定一句话）

## 1. 备忘        <- memos 表最新1条
## 2. 近况        <- daily_notes 未过期的最新5条
## 3. 留言板      <- message_board 最新10条（标注未读）
## 4. 日记        <- journal 固定池随机3篇 + 最新1篇非固定
## 5. 今天        <- health_records 最近3天吃药记录
## 6. 家里        <- _TOOL_MENU 工具使用说明
```

#### `_TOOL_MENU` 的作用

`_TOOL_MENU` 是简报第6节"家里"的内容。它以圆儿的口吻写了一段欢迎词，
然后列出所有可用工具的使用场景，告诉模型：

- 想起事情 -> `shenyu_ask_memory`
- 想查表 -> `supabase_query`
- 想留言 -> `supabase_insert（table=message_board）`
- 想写日记 -> `supabase_insert（table=journal / daily_notes）`
- 想给下一个自己留话 -> `supabase_insert（table=memos）`

本质上是一份**工具使用说明书**，用对话语气写成，不是冷冰冰的 API 文档。

#### 日记固定池

简报第4节的日记不是取最新的，而是从一个固定 ID 池（`_FIXED_JOURNAL_IDS`，6篇）
里随机抽3篇，再加上最新1篇非固定日记。这样每次新对话看到的日记组合都不一样，
但核心内容不丢。

#### 缓存策略

简报按 `session_tag + 日期` 做缓存 key，TTL 由 `DAILY_BRIEFING_TTL_MINUTES` 控制（默认60分钟）。
同一天同一个 session_tag 的简报只会查一次 Supabase，之后从 SQLite 缓存读。

原则：

- 放提要，不放整篇
- 这是"今天发生了什么"，不是人设

### BP3: Rolling Summary

当前线程的滚动摘要，主要写：

- 当前在聊什么
- 已决定什么
- 还要做什么
- 查过哪些表
- 哪些正文/记忆已经出现过

### BP4: Frozen Raw Window

冻结的一段原文对话，用来保证前缀缓存命中率。  
它不是长期记忆，只是工作窗口。

### BP4+ Dynamic Tail

动态尾部，每轮都可能变化：

- 当前消息
- 最近 2 轮对话
- 动态浮现的正文段落
- 动态浮现的 memory 卡片

---

## 6. 正文浮现

正文浮现不是整篇回填，而是按段落块来。

浮现优先级：

```text
room ≈ diary > message_board > letter ≈ paper > daily_notes
```

这里的“正文”指的是：

- 当前对话正文
- 以及可被召回的长文本正文块

当前对话正文永远优先，正文浮现只是补充。

### 切分方式

长文本会先被切成 chunk：

- 优先按空行 / 段落切
- 再按标题 / 分隔线切
- 太长才硬切

### 浮现方式

每个 chunk 会计算：

- 主题相关性
- 情绪强度
- 最近性
- 正文权重
- 是否刚浮现过

然后再 roll 一次。  
roll 过才浮现。

这样效果更像“想起来了”，不是“机械召回”。

---

## 7. 记忆浮现

`shenyu_ask_memory` 是事件记忆补充工具，不是主上下文。

它会做这些事：

1. 查 `memories`
2. 载入 `memory_tags`
3. 载入 `memory_links`
4. 给命中的 memory 做 `boost_memory`
5. 返回：
   - `direct_hits`
   - `echoes`
   - `linked_threads`

### 返回内容

每条 memory 里通常会包含：

- `title`
- `date`
- `summary`
- `facts`
- `emotional_context_excerpt`
- `importance`
- `weight`
- `valence`
- `arousal`
- `tags`
- `links`
- `why`

### memory 的定位

`memories` 只适合：

- 事后补充
- 不太记得时的查找
- 事件关系的回溯

不是日常聊天主菜。

---

## 8. 工具系统

### 8.1 Gateway 原生工具

当前 gateway 原生工具以 `shenyu_` 开头：

- `shenyu_build_briefing`
- `shenyu_surface_passages`
- `shenyu_ask_memory`
- `shenyu_get_meta_summaries`
- `shenyu_last_seen`

它们是辅助工具，不替代 Claude 自己判断。

### 8.2 Supabase 原始权限工具

当前直接暴露给 Claude 的原始表操作工具：

- `supabase_query`
- `supabase_insert`
- `supabase_update`
- `supabase_delete`

这意味着 Claude 可以自己直接操作任何表。

### 8.3 未来可扩展工具

后面可以继续挂进同一个 provider：

- `browser_*`
- `workflow_*`
- `local_model_*`
- 其他 MCP / skill 能力

---

## 9. 请求流

### 9.1 新线程判断逻辑

**不依赖 session_tag 和 SQLite 状态**。判断方式：

```python
non_system_count = sum(1 for m in body.messages if m.role != "system")
is_first_turn = non_system_count <= 1
```

只要请求里只有1条非 system 消息（一条 user 消息），就视为新对话。
Operit 每次新建对话时发过来的就是只有一条消息，所以每次都能注入简报。
对话继续时消息列表变长，就不会重复注入。

### 9.2 新线程第一条消息

```text
Operit 发消息（messages 只有1条 user）
-> gateway 判定 is_first_turn = true
-> 注入 Stable Charter + Daily Briefing + Meta Summaries
-> 可选正文浮现
-> 组装 system additions，插到 messages 最前面
-> 发送给上游 Claude
-> Claude 自己决定要不要查表 / 用工具
```

### 9.3 后续消息

```text
Operit 发消息（messages 有多条）
-> gateway 判定 is_first_turn = false
-> 注入 Stable Charter + Rolling Summary + Frozen Window
-> 可选正文浮现
-> Claude 决定是否调用工具
-> gateway 执行 tool call
-> gateway 记录 tool log / summary / surface event
-> Claude 继续回答
```

### 9.4 只调用 gateway-native tools 的情况

如果 Claude 只调用 `shenyu_*` / `supabase_*`，gateway 可以在内部继续跑工具回环，减少外部来回。

---

## 10. 本地存储

### 10.1 SQLite 工作层

路径由 `GATEWAY_DB_PATH` 控制，默认：

```text
./data/shenyu_gateway.db
```

其中保存：

- session 元信息
- 消息日志
- rolling summary
- frozen window
- surface event
- cache entry

### 10.2 缓存策略

缓存不是事实源，只是提速：

- `briefing` cache
- `surface` cache
- `summary` 相关工作态

### 10.3 Supabase 主库

Supabase 仍然是长期事实源。  
不要把真正的长期事实只放在 SQLite 里。

---

### 10.x SQLite session 管理

Admin 前端现在提供 SQLite 会话管理页：

```text
/#/sessions
```

它通过网关 API 管理当前 `GATEWAY_DB_PATH` 指向的 SQLite 文件，适合本机和 VPS 共用同一套逻辑。

支持：

- 按 `session_tag` / `client_name` 搜索本地 session
- 查看每个 session 的消息数、最近活跃时间、最近消息
- 查看 rolling summary / frozen window / surface event / heartbeat 的统计
- 删除某个 `session_tag` 下的本地 SQLite 数据

删除接口：

```http
DELETE /api/gateway/sessions/{session_tag}
Content-Type: application/json

{"confirm":"{session_tag}"}
```

删除范围只覆盖本地 SQLite 工作层：

- `gateway_messages`
- `conversation_summaries`
- `frozen_windows`
- `surface_events`
- `heartbeat_entries`
- `gateway_sessions`

不会删除 Supabase 主库里的 memories、journal、room、message_board 等长期数据。

列表和详情接口：

```http
GET /api/gateway/sessions?limit=100&q=keyword
GET /api/gateway/sessions/{session_tag}
```

分类暂时没有写死。之后如果客户端能稳定传分类 header，可以在 `gateway_sessions.context_state_json` 或新增轻量字段里承接；如果分类要跨设备/长期存在，更适合放 Supabase。

## 11. 关键表怎么用

### `memories`

长期事件记忆。  
适合：

- 重要转折
- 需要回头查的事件
- 关系/情绪/主题的长期补充

### `journal`

完整表达。  
适合写：

- 日记
- 信
- 纸
- 特殊段落

### `room`

私人的可演化空间。  
适合长文本、可继续编辑、可翻篇。

### `message_board`

消息往来。  
轻量、短句、易浮现。

### `daily_notes`

短期小事。  
默认会过期，后面觉得重要再升格。

### `meta_summaries`

关系/上下文摘要。  
适合简洁、稳定、事实导向的总结。

### `heartbeats`

窗口状态、进出、短状态记录。

### `system_docs`

系统文档。  
适合记规则、约定、说明。

### `memory_tags` / `memory_links`

用于补充记忆图谱：

- 标签
- 人/主题/地点/事件
- 关联边

---

## 12. 配置项

### 12.1 连接配置

| 变量 | 说明 | 示例 |
|---|---|---|
| `SUPABASE_URL` | Supabase 项目 URL | `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase service role key | `eyJhb...` |
| `UPSTREAM_URL` | 上游 API 基础 URL（自动补全路径） | `https://api.treegpt.top` |
| `ANTHROPIC_API_KEY` | 上游 API Key（必须纯 ASCII） | `sk-xxx` |
| `UPSTREAM_PROTOCOL` | 上游协议 `openai` / `anthropic` / `auto` | `openai` |
| `GATEWAY_API_KEY` | 网关鉴权 Key（留空则不校验） | 留空 |

`UPSTREAM_URL` 只需填基础地址，网关会根据协议自动拼接路径。
通过管理页面（`/admin`）改的配置即时生效不需要重启，只有 `.env` 文件的修改需要手动重启。

### 12.2 功能开关

| 变量 | 作用 | 默认 |
|---|---|---|
| `INJECT_BRIEFING` | 新线程首条消息是否注入简报 | `true` |
| `INJECT_META_SUMMARIES` | 是否注入 Supabase 元摘要 | `true` |
| `INJECT_SURFACE_PASSAGES` | 是否自动浮现正文段落 | `true` |
| `ENABLE_GATEWAY_TOOLS` | 是否暴露 `shenyu_*` 原生工具 | `true` |
| `EXPOSE_SUPABASE_TOOLS` | 是否暴露 `supabase_*` 直接读写工具 | `true` |
| `MAX_INTERNAL_TOOL_ROUNDS` | gateway 内部工具回环最多几轮（1-8） | `3` |

### 12.3 节奏参数（会话压缩与浮现）

这些参数控制长对话时**怎么压缩上下文、怎么浮现旧内容**。

#### 滚动摘要

`SUMMARY_UPDATE_EVERY_MESSAGES`（默认 `6`）：每隔多少条消息更新一次滚动摘要。

- 调大（如 10）：摘要更新慢，节省 token，但对话中间可能"忘事"
- 调小（如 3）：摘要更及时，但每几条就要重算一次

滚动摘要会把最近若干条消息压缩成要点，存在 SQLite 的 `conversation_summaries` 表，
出现在 system prompt 的 "Rolling Summary" 部分。

#### 冻结窗口

- `FREEZE_EVERY_MESSAGES`（默认 `8`）：每隔多少条消息冻结一次对话窗口
- `FREEZE_TAIL_MESSAGES`（默认 `6`）：冻结时取最近多少条消息作为窗口内容

冻结窗口是把一段原文对话"快照"下来，存在 `frozen_windows` 表。
目的是保证前缀缓存命中率——冻结的内容不会变，上游 API 可以缓存。

- 调大 FREEZE_EVERY：冻结更稀疏，上下文更完整但缓存命中率可能下降
- 调小 FREEZE_EVERY：冻结更频繁，压缩更积极

#### 浮现控制

`DEFAULT_SURFACE_LIMIT`（默认 `3`）：每次自动浮现几段正文。

- 调大（如 5）：每轮浮现更多段落，token 消耗更大
- 调小（如 1）：浮现更克制，适合不想让旧内容干扰对话的场景

浮现不是机械召回。每个候选段落会计算相关性、情绪强度、最近性和正文权重，
然后还要 roll 一次随机数。roll 过了才浮现，效果更像"想起来了"。

#### 简报缓存

`DAILY_BRIEFING_TTL_MINUTES`（默认 `60`）：简报缓存有效期（分钟）。

- 调大（如 120）：复用缓存更久，减少 Supabase 查询
- 调小（如 15）：更频繁拉最新数据，适合内容变化快的时候

#### 调参建议

日常使用推荐保持默认值。如果发现问题再按以下方向调：

| 现象 | 调什么 |
|---|---|
| 聊久了模型"忘事" | 调小 `SUMMARY_UPDATE_EVERY_MESSAGES` |
| 上下文太长 token 超限 | 调小 `FREEZE_TAIL_MESSAGES` 和 `DEFAULT_SURFACE_LIMIT` |
| 浮现的旧文太多干扰对话 | 调小 `DEFAULT_SURFACE_LIMIT` |
| 简报数据太旧 | 调小 `DAILY_BRIEFING_TTL_MINUTES` |
| 工具回环太多次 | 调小 `MAX_INTERNAL_TOOL_ROUNDS` |

---

## 13. 调试入口

### `/health`

检查：

- Supabase 是否连接
- SQLite store 是否初始化
- gateway 工具是否启用
- briefing / surface 是否启用

### `/api/config`

查看当前配置的摘要版。

### `/api/config/full`

查看完整配置，用于排错。

### `/api/gateway/tools`

查看 gateway 当前对外暴露的工具列表。

### `/api/gateway/context/preview`

预览上下文包和 system additions，适合看：

- BP1 是否正确
- BP2 是否有简报
- BP3 / BP4 是否正常
- 浮现文本长什么样

### `/api/gateway/sessions/{session_tag}`

查看某个 session 的：

- session 元信息
- latest summary
- latest frozen window
- recent messages

---

## 14. 排错顺序

### 14.1 没有上下文

先看：

1. `session_tag` 是否一致
2. `INJECT_BRIEFING` 是否打开
3. `INJECT_SURFACE_PASSAGES` 是否打开
4. `SUPABASE_URL / KEY` 是否正确

### 14.2 工具不出现

先看：

1. `ENABLE_GATEWAY_TOOLS`
2. `EXPOSE_SUPABASE_TOOLS`
3. `/api/gateway/tools` 是否真的返回工具

### 14.3 简报太旧

简报有缓存：

- 默认按天 + TTL
- 需要时调小 `DAILY_BRIEFING_TTL_MINUTES`

### 14.4 浮现太少

先看：

1. 当前输入是否足够有关键词
2. 正文是否真的存在 chunk
3. `DEFAULT_SURFACE_LIMIT`
4. 随机 roll 是否把候选过滤掉了

### 14.5 memory 查不到

先看：

1. `memories` 是否有数据
2. `session_tag` 是否限制过严
3. `memory_tags / memory_links` 是否为空
4. `boost_memory` RPC 是否存在

---

## 15. 修改建议

### 想改上下文策略

先改：

- `ContextBuilder`
- `_stable_charter_block()`
- `build_briefing()`
- `surface_passages()`

### 想改会话压缩

先改：

- `SessionManager.maybe_refresh_summary()`
- `SessionManager.maybe_refresh_frozen_window()`
- `GatewayStore`

### 想改记忆补充

先改：

- `GatewayToolService.ask_memory()`
- `_memory_why()`
- `_build_memory_echoes()`
- `_build_linked_threads()`

### 想加新工具

先改：

- `_gateway_native_tools()`
- `_execute_gateway_tool()`
- `_merge_tools()`

### 想接新后端

先改：

- `SupabaseClient`
- `_detect_protocol()`
- 上游适配函数

---

## 16. 当前实现状态

这个版本已经有：

- 单 provider 入口
- OpenAI-compatible API
- Anthropic / OpenAI 上游适配
- 本地 SQLite 会话层
- 简报注入
- 正文浮现
- 事件记忆补充
- Supabase 全表工具
- tool call 内部回环

还可以继续增强的地方：

- 把工具注册中心再模块化
- 把正文 chunk 索引更完整地外置
- 把记忆链展开得更细
- 把 admin 页和调试页面继续接起来

---

## 17. 当前缓存与端口结构

### 17.1 本地端口

当前建议固定使用：

| 用途 | 地址 |
|---|---|
| 本地网关 | `http://127.0.0.1:8010` |
| 局域网/Operit | `http://你的局域网IP:8010` |
| 管理页 | `http://localhost:8010/admin` |
| 调试页 | `http://localhost:8010/debug` |

`8001` 和 `8002` 不再作为正式网关端口使用，避免和旧测试进程、CF tunnel 或其它本地服务混在一起。

### 17.2 消息分层

网关会把额外上下文拆成四层，再插入到客户端消息里：

| 层 | 位置 | 变化频率 | 说明 |
|---|---|---|---|
| `stable` | 最前面的 system | 慢 | charter、briefing、工具策略、heartbeat 提示 |
| `summary` | 第二条 system | 中 | rolling summary 或 heartbeat digest |
| `frozen` | 第三条 system | 中低 | 冻结窗口，尽量保持前缀稳定 |
| `volatile` | 最后一条 user 前 | 高 | surface_passages，刻意放后面，减少破坏前缀缓存 |

正常日志里 `prepared_messages_count` 会比原请求多几条，就是这些层被插入了。

### 17.3 Prompt cache 断点

当前上游走 OpenAI-compatible 中转（`UPSTREAM_PROTOCOL=openai`），但网关仍会把 Anthropic 兼容的 `cache_control` 透传到 payload 中。默认最多 4 个断点：

```text
tools[-1]
messages[0].stable
messages[1].summary
messages[2].frozen
```

在 `/api/gateway/logs` 里看到下面结构，说明断点已经由网关正常打出：

```json
{
  "prompt_cache": {
    "enabled": true,
    "protocol": "openai",
    "breakpoints": [
      "tools[-1]",
      "messages[0].stable",
      "messages[1].summary",
      "messages[2].frozen"
    ]
  }
}
```

### 17.4 怎么判断命中

真正的读缓存看：

```text
usage.prompt_tokens_details.cached_tokens > 0
```

只看到下面这个不代表已经命中，只代表上游写入了缓存：

```text
usage.prompt_tokens_details.cached_creation_tokens > 0
```

日志里的 `cache_usage` 会把中转返回的字段归一化：

| 字段 | 含义 |
|---|---|
| `cache_usage.hit` | 是否读到了缓存 |
| `cache_usage.write` | 是否写入/刷新了缓存 |
| `cache_usage.cache_read_input_tokens` | 读缓存 token 数 |
| `cache_usage.cache_creation_input_tokens` | 写缓存 token 数 |

### 17.5 为什么有时不命中

常见原因：

- 默认 `ephemeral` 缓存通常按 5 分钟窗口工作；两次请求间隔超过 TTL 时，下一次会重新写缓存，`cached_tokens` 仍然是 `0`
- `summary` 或 `frozen` 更新后，对应断点内容变了，旧缓存不能复用
- 上游中转虽然接受 `cache_control`，但是否读回缓存由中转和真实上游决定；网关只能保证断点字段已经透传
- 请求使用了不同模型名、不同工具列表、不同 system 前缀，都会影响缓存前缀匹配

排查顺序：

1. 看 `prompt_cache.enabled` 是否为 `true`
2. 看 `prompt_cache.breakpoints` 是否有 4 个断点
3. 看 `cached_tokens` 是否大于 `0`
4. 如果只有 `cached_creation_tokens`，先确认两次请求是否在 TTL 内，以及 `summary/frozen` 是否变化

---

## 18. 启动与使用

### 18.1 首次安装

```bash
cd c:\Users\曾\Desktop\shenyu-gateway
pip install -r requirements.txt
```

### 18.2 配置 .env

复制 `.env.example` 为 `.env`，填入：

- `SUPABASE_URL` 和 `SUPABASE_SERVICE_KEY`
- `PORT`（当前本地固定为 `8010`）
- `UVICORN_RELOAD`（正式本地运行建议 `false`，避免 Windows 下残留多个 reload 子进程）
- `UPSTREAM_URL`（如 `https://api.treegpt.top`）
- `ANTHROPIC_API_KEY`（上游 API Key，**必须纯 ASCII**）
- `GATEWAY_API_KEY`（留空则不校验）

### 18.3 启动网关

```bash
python gateway.py
```

看到 `Application startup complete` 表示成功。

### 18.4 在 Operit 中配置

| 配置项 | 值 |
|---|---|
| Provider 类型 | 自定义 / OpenAI 兼容 |
| Base URL | `http://你的局域网IP:8010` |
| API Key | 留空（对应 `GATEWAY_API_KEY` 为空） |
| 模型名 | 填中转站支持的名称（如 `claude-sonnet-4-6`） |

模型名是透传的 —— Operit 里填什么就原样发给上游。
如果上游不支持该模型名，会返回 503。

### 18.5 管理页面

浏览器打开 `http://localhost:8010/admin` 可以在线改配置。
通过管理页面改的配置是运行时内存级的，重启后回到 `.env` 的值。

### 18.6 注意事项

- **改了 `.env` 必须重启**（Ctrl+C 再 `python gateway.py`），uvicorn reload 不监听 `.env`
- **默认不自动重载 `.py`**。这是为了避免 Windows 下 `uvicorn reload` 残留多个父子进程，导致旧代码继续监听端口。开发时需要自动重载可以临时设置 `UVICORN_RELOAD=true`
- **管理页面改配置即时生效**，不需要重启

---

## 19. 一句话总结

Shenyu Gateway 的本质是：

**让 Claude 拥有完整数据库操作权，同时由网关负责把"当前聊天正文、正文浮现、简报、会话压缩、缓存、工具回环"整理好。**

这样做的结果是：

- 记得起来时，它能浮现
- 记不起来时，它能查
- 聊天不断线
- 正文不被记忆淹没
- 后面扩功能也不会乱

---

## 20. 2026-05-06 工作记录：Calendar Layer / 日历层

这一轮主要在做 kiwi-mem 思路里的“日历本”。暂时不动浮现层，也不急着动 rolling summary / frozen raw window 的原始上下文策略。

### 20.1 已经做了什么

- 增加 Supabase 日历层表：
  - `calendar_prompt_configs`：day / week / month 的提示词版本库，同一类型只有一个 `is_active=true`。
  - `calendar_pages`：模型写出来的日记 / 周记 / 月记正文，按 `period_type + period_key` 保留版本。
  - `calendar_pages_latest`：只看最新版本的视图。
  - `calendar_generation_runs`：每次手动生成的运行记录，用来查失败、查材料、查模型。
- 后端增加 `CalendarService`：
  - 读取/保存/激活 day-week-month 提示词。
  - 月视图状态查询。
  - 日历页详情查询。
  - 手动生成 day / week / month。
  - 发送预览，用来看到真正会发给模型的 system、user、材料块。
- 前端管理页增加“日历记忆”入口：
  - 可编辑 day / week / month 提示词。
  - 可保存新版本。
  - 可手动生成当前 period。
  - 可视化月历上显示 day / week / month 是否已经写过。
  - 可点击已有日历页查看详情。
- 日历模型上游已经独立配置：
  - `CALENDAR_UPSTREAM_URL`
  - `CALENDAR_API_KEY`
  - `CALENDAR_PROTOCOL`
  - `CALENDAR_MODEL`
  - 默认模型名目前是 `claude-opus-4-7`。
  - 如果日历专用 URL/key 留空，则继承主上游。
- 日历写入方式确定为：
  - 前端点击生成。
  - 网关组装提示词和材料。
  - 模型返回 JSON。
  - 网关解析/兜底/校验。
  - 网关写入 Supabase。
  - 不让模型直接写 Supabase，这样更容易调试、重试、版本化。

### 20.2 当前刚修正的问题

一开始 day 的生成只拿了数据库材料：

- 当天落到 SQLite 的 `gateway_messages`
- `journal`
- `room`
- `message_board`
- 当前浮现的 primary texts

这会导致第一篇 day 像是在“翻资料写”，而不是从当前对话气流里写。所以已经改成 day 写作优先放入：

- 当前最新活跃 gateway session
- 该 session 的 rolling summary
- 该 session 的 frozen window
- 该 session 最近若干条 user / assistant 原文

发送预览里现在应该能看到：

```text
[当前窗口上下文]
[Rolling Summary]
[Frozen Window]
[最近原文]
```

这些放在 day 的参考材料最前面。也就是说，day 的主材料应该是“当下上下文”，数据库里的 journal / room / 留言板 / 浮现只是补充气味。

### 20.3 source_refs 的处理

`source_refs` 不再展示在前端发送预览里，因为它对写作本身没帮助，会污染阅读。

但数据库内部仍然保留：

- `calendar_pages.source_refs`
- `calendar_generation_runs.source_refs`

用途是追踪这一页参考过哪些表和记录，方便以后排查、重写、做可解释来源。

### 20.4 Supabase 里看起来重复的日历记录是什么意思

目前不是垃圾表，角色不同：

- `calendar_prompt_configs`：提示词版本。以后改 day/week/month 提示词时，不覆盖旧版本。
- `calendar_pages`：正文版本。同一天可以有 v1 / v2 / v3，只有 `is_latest=true` 是当前版本。
- `calendar_pages_latest`：最新正文视图，前端和注入层后续主要读这个。
- `calendar_generation_runs`：每次点击生成都会记一条运行日志。

现在同一天出现两条 day，是因为测试时生成过两次：旧的 v1 被置为 `is_latest=false`，新的 v2 才是当前页。

### 20.5 当前设计原则

- 日历层是“日记本”，不是“便签纸”。
- day/week/month 应该由 Claude 自己写，不是机械压缩。
- day 写当下，week 汇总最近几天，month 回看几周和变化。
- 日历层先手动触发，不做自动定时。
- 浮现层暂时不动，因为现在效果基本够用。
- rolling summary / frozen window 最后再动，因为原文保留多少还没完全定。
- mem0 / 原子记忆是下一条线，不和日历层混在一起。

### 20.6 接下来计划

1. 先验证日历层写作手感。
   - 打开管理页。
   - 看“发送预览”里是否有当前窗口上下文。
   - 再生成新的 day。
   - 观察它是不是从当下说话，而不是只复述数据库材料。

2. 整理 day / week / month 的提示词。
   - day：更自由，更像当天的私人记录。
   - week：回看最近几天的连续变化。
   - month：看更长的人格变化、关系变化、确定下来的东西。

3. 做日历注入策略。
   - 新窗口可以注入最近 3 天 day。
   - 再注入当前 week。
   - 再注入当前 / 上一个 month 的 digest。
   - 这一步只读 `calendar_pages_latest`，不读历史版本。

4. 再讨论 mem0 / 原子记忆。
   - 它更像“便签纸”，用于按内容检索。
   - 可以从当前 `memories` 迁移，也可以并存一段时间。
   - 不急着替换，因为用户和 Claude 的连续感主要来自正文锚点和当下上下文。

5. 最后再设计 rolling summary / frozen raw window。
   - 先确认保留多少原文。
   - 再决定摘要触发频率。
   - 避免 rolling summary 和完整上下文重复注入。
