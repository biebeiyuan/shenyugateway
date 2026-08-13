# MCP 外部工具接入 · 实施与交接文档（2026-08-13）

状态：**已完成，留档**。实施工作区曾为 `/home/yuan/worktrees/mcp-config`（分支 `mcp-config`，
基于 master `8b4b4d9`），已合并回 master。本文保留当时的设计与实施记录；
当前事实以 README Maintenance Map 与代码为准。交付规则见 `docs/DELIVERY.md`。

## 一、目标与设计（已与 owner 商定）

让网关作为 MCP **client** 连接若干外部 MCP server（streamable HTTP / SSE），远端工具并入
现有工具管线：模型在内部工具环直接调用，Admin/PWA 可配置 server 列表、看状态、测连接。

- SDK：`mcp` 2.0.0（已在 `.venv`）。`Client(url)` 即 streamable HTTP，`mode='auto'` 自带
  era 协商；`call_tool` 结果含 `is_error` / `structured_content` / `content`。
- 配置源：环境变量 `MCP_SERVERS`（JSON 数组），走 `persist_env` 持久化（同 `/api/config`）。
  每项 `{"name", "url", "transport": "auto|sse", "headers": {}, "enabled": true}`；
  `name` 限 `[a-z0-9_]{1,24}`，重名报错。
- 命名：远端工具暴露为顶层 function tool `mcp_<server>_<tool名清洗后>`，**不进 broker**。
  `is_gateway_native_tool` 增加 `mcp_` 前缀 → 纯 MCP 批次留在内部工具环执行，混合批次
  走既有 `_execute_mixed_gateway_tool_calls` 路径（无需改动，靠前缀识别）。
- 工具列表缓存：`mcp_registry.registry`（进程内单例）持快照，TTL `mcp_tools_cache_seconds`
  （默认 300s）。`prepare_messages`（async）里 `ensure_fresh()`：无快照→同步刷新一次；
  快照过期→后台刷新不阻塞。`merge_tools`（sync）只读快照。server 挂了记状态，不 500。
- 执行：`execute_gateway_tool` 的 `mcp_` 分支 → 每次调用临时建连
  （`asyncio.timeout`，`mcp_call_timeout_seconds` 默认 60s），错误统一
  `{"ok": False, "error", "error_kind"}`（timeout / mcp_connection / mcp_tool_error / validation）。
- N 轮裁剪：`context_layers.trim_mcp_tool_results`——按暴露名分组，每组最近
  `mcp_tool_result_keep_recent`（默认 3）条完整保留，更早且 ≥600 字符的替换为一行 stub
  `[<tool> 的历史结果已省略，如需数据请重新调用]`。在包裁剪之后调用，trim_meta 记
  `mcp_tool_results_seen/compressed`。
- 路由：`/api/mcp/*`（`/api/` 前缀自动走 admin 鉴权中间件）。

## 二、已完成改动（本 worktree 未提交，`git status` 可见）

1. **`shenyu_gateway/mcp_registry.py`（新文件，完整）**
   - `validate_mcp_servers(raw)`：校验/规范化 server 列表，ValueError 带中文原因。
   - `McpToolRegistry`：`tools_for_merge(cfg)`（sync 读快照，按 enabled 过滤）、
     `status()`、`tool_summaries()`、`invalidate()`、`ensure_fresh(cfg)`、`refresh(cfg)`
     （逐 server `_list_server`，失败进 status 不抛）、`execute(name, args, cfg=...)`
     （未知名先 refresh 一次再报错）、`test_server(server, cfg=...)`（一次性探测，不碰快照）。
   - 模块级单例 `registry`。SDK 惰性导入（`_build_client`），SDK 缺失不挡启动。
   - headers 支持：sse 走 `sse_client(url, headers=...)`；streamable HTTP 带 headers 走
     `create_mcp_http_client(headers=...)` 注入。
2. **`shenyu_gateway/config.py`**：新增 `enable_mcp_tools`（`ENABLE_MCP_TOOLS`，默认 true）、
   `mcp_servers`（`_load_mcp_servers()`，坏 JSON 只 warning 不挡启动）、
   `mcp_call_timeout_seconds`(60, 5–600)、`mcp_list_timeout_seconds`(10, 2–120)、
   `mcp_tools_cache_seconds`(300, 10–86400)、`mcp_tool_result_keep_recent`(3, 0–50)；
   `to_dict()` 已加这些字段，`mcp_servers` 的 headers 值用 `mask()` 打码。
3. **`shenyu_gateway/schemas.py`**：`ConfigUpdate` 加 5 个可选字段（不含 mcp_servers，
   server 列表走专用路由）。
4. **`shenyu_gateway/config_routes.py`**：`_full_config` 加 5 字段；`env_names` 加 5 映射；
   `enable_mcp_tools` 进 `simple_fields`；4 个 int 字段加了钳制写回段（同现有风格）。
5. **`shenyu_gateway/tool_registry.py`**：`merge_tools` 末尾追加 MCP 快照工具（去重）；
   `is_gateway_native_tool` 加 `mcp_` 前缀；`execute_gateway_tool` 开头加 `mcp_` 分支
   （惰性导入 registry，避免循环依赖）。
6. **`shenyu_gateway/context_layers.py`**：`_MCP_RESULT_MIN_CHARS = 600`；
   新函数 `trim_mcp_tool_results(messages, keep_recent)`。
7. **`shenyu_gateway/prepare_messages.py`**：导入 `trim_mcp_tool_results` 和
   `_mcp_registry`；在包裁剪后调用 MCP 裁剪；随后 `await _mcp_registry.ensure_fresh(cfg)`。

## 三、剩余步骤（按序执行）

### 3.1 先核对 SDK 属性名（10 分钟，必做）

`mcp_registry._list_server` 假设 `listed.tools[i]` 有 `name/description/input_schema`。
写此段时未验证 `input_schema` 还是 `inputSchema`。核对：

```bash
source /home/yuan/shenyu-gateway/.venv/bin/activate
python -c "import mcp_types; import inspect; print([f for f in mcp_types.Tool.model_fields])"
```

同时核对 `sse_client(url, headers=...)` 与 `streamable_http_client(url, http_client=...)`
的实际签名（`inspect.signature`）。不符就改 `_build_client` / `_list_server`。

### 3.2 `shenyu_gateway/mcp_routes.py`（新文件）

参照 `calendar_routes.py` 的 frozen dataclass Deps 风格：

- `McpRouteDeps`: `cfg`, `persist_env: Callable[[dict], None]`。
- `GET /api/mcp/servers` → `{"servers": [headers 打码], "status": registry.status(), "tools": registry.tool_summaries()}`。
- `POST /api/mcp/servers`（全量替换）→ `validate_mcp_servers`（ValueError → 400）；
  **打码回传问题**：新列表里某 server 的 header 值若等于打码占位（`****` 开头结尾），
  沿用 `cfg.mcp_servers` 中同名 server 同 key 的旧值；然后
  `cfg.mcp_servers = servers`、`deps.persist_env({"MCP_SERVERS": json.dumps(servers, ensure_ascii=False)})`、
  `registry.invalidate()`。
- `POST /api/mcp/refresh` → `await registry.refresh(cfg)`，返回 status。
- `POST /api/mcp/test`（body 是单个 server 对象）→ `validate_mcp_servers([body])` 后
  `registry.test_server(...)`。
- `gateway.py`：import + `app.include_router(build_mcp_router(McpRouteDeps(cfg=cfg, persist_env=_persist_env_with_store)))`，
  挂在 config router 附近（约 660 行）。

### 3.3 后端测试 `tests/test_mcp_tools.py`（新文件）

参照现有测试用 fake/monkeypatch，不出网：

1. `validate_mcp_servers`：合法、坏 name、重名、坏 url、坏 transport、字符串 JSON 输入。
2. `trim_mcp_tool_results`：keep_recent=1 时旧大结果变 stub、新结果保留；
   非 MCP tool 结果不动；<600 字符不压；keep_recent=0 全压。
3. `merge_tools`：monkeypatch `mcp_registry.registry._tools` 塞快照 → 出现在结果里；
   `enable_mcp_tools=False` 时不出现；与 client 工具重名去重。
4. `execute_gateway_tool("mcp_x_y", ...)` 分发到 `registry.execute`（monkeypatch）。
5. `is_gateway_native_tool("mcp_a_b") is True`。
6. mcp_routes：TestClient 挂 router，GET 打码、POST 替换+持久化（fake persist_env 收集）、
   POST 保留打码 header 旧值、test 端点（monkeypatch `_list_server`）。
7. registry 单测：`_normalize_call_result`（is_error / structured_content / 纯文本）、
   `refresh` 全挂时 status 有 error 且 tools 空、`execute` 未知工具报 validation。

### 3.4 全量回归

```bash
cd /home/yuan/worktrees/mcp-config && source /home/yuan/shenyu-gateway/.venv/bin/activate
python -m pytest tests/ -x -q
```

基线必须全绿（AGENTS.md：失败先归因，master 树有邻座 agent 在改 `streaming.py`，
本 worktree 与之隔离，不应互相影响）。

### 3.5 Admin/PWA 面板（task #13）

- 先探 `admin/src` 现有 config 页面结构，照现有 section 风格加「MCP 服务器」卡片：
  列表（name/url/transport/enabled/状态灯/工具数/最后检查时间）、增删改表单
  （headers 键值对）、「测试连接」按钮（POST /api/mcp/test）、「刷新工具」按钮、
  数值项（4 个超时/缓存/裁剪配置）并入现有配置表单。
- vitest：列表渲染、表单校验（name 正则、url 前缀）、打码 header 不回传原值。
- 视觉检查用 `cd admin && npm run preview:isolated`（AGENTS.md 规定，不连真实凭据）。

### 3.6 收尾（task #14）

1. 文档：README 产品段落 + `docs/`（若有工具/配置清单文档则同步；本文件留档 history）。
2. `python scripts/resident_home.py check` → 对 `review_required` 组件逐个
   `review --summary ... --impact ...`（impact 以「你…」开头，称呼**沈予**）；
   纯共享文件组件用 `ack-shared`。
3. 全部通过后一次提交（只 stage 本任务文件），同日合并回 master：
   合并前 `git -C /home/yuan/shenyu-gateway status` 归因外来改动（已知 `streaming.py`
   是邻座的，**不要动它**），`git merge mcp-config` 后跑基线。
4. `python scripts/project_delivery.py record ...`：绑 README 产品、changed paths、
   verification 一行基线结论 + 本次特有证据、按 `docs/DELIVERY.md` 四级阶梯定 status
   （只有单测+isolated 预览 → 对应较低档；连上真实外部 MCP server 验证过再升档）。

## 四、验收标准

- [ ] `pytest tests/ -q` 全绿（含新增 MCP 测试）。
- [ ] 配置了一个假 URL 的 server 时：网关照常启动、聊天不 500、
      `GET /api/mcp/servers` 的 status 显示该 server error。
- [ ] 连一个真实 MCP server（可用官方 everything server 本地起）：
      `mcp_<server>_<tool>` 出现在 merge_tools 输出；模型调用返回真实结果；
      工具结果超过 3 条旧的被 stub 替换（看 request log 的 trim_meta）。
- [ ] Admin 面板能增删改测 server，header 值不明文回显。
- [ ] `MCP_SERVERS` 写进 `.env`，重启后配置仍在。
- [ ] resident_home review + delivery 记录完成，worktree 已合并、分支可删。

## 五、坑与注意

- `config.py._load_mcp_servers` 惰性导入 `mcp_registry`（防循环导入）；
  `tool_registry`/`prepare_messages` 同理，改动时保持惰性导入。
- `registry` 是进程内单例，多 worker 部署各自有快照——可接受，勿引入跨进程缓存。
- MCP 工具故意不进 broker（`shenyu_gateway_tool` 的 enum 不含它们）。
- 混合批次（MCP + client 工具同批）走 `_execute_mixed_gateway_tool_calls`，
  靠 `is_gateway_native_tool` 前缀识别，已覆盖，无需改流式/非流式循环本体。
- owner 已确认隔离方式：本 worktree 独立分支；master 树同时有另一 agent 在干活。
