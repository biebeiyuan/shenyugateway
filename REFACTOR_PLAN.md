# Shenyu Gateway 结构重构方案（Codex 修订版）

> 目标：每个核心源文件尽量 ≤ 800 行，职责单一，agent 可在单次上下文内完整理解任意文件。
> 原则：纯搬运 + 改 import/依赖注入，不改业务逻辑。每步完成后跑测试确认不破坏。

本文是在 Claude 原方案基础上的修订版。总体方向保留，但修正了当前工作区行数、依赖来源、模块边界和执行顺序。

---

## 当前现状（2026-07-01 更新）

- `gateway.py`：~740 行（从 1157 行大幅缩减）。chat pipeline、streaming、tool loop、routes 等已拆出。
- `shenyu_gateway/tool_registry.py`：~928 行（从 1486 行缩减）。tool_schemas 已拆出。
- `shenyu_gateway/mem_notes/`：已从 1595 行单文件拆成 mixin 包（按 stars/ 模式），各文件均 ≤ 570 行：
  - `__init__.py`（~45 行）：组装 MemNoteService，re-export 向后兼容符号
  - `_helpers.py`（~105 行）：常量、ID 规范化、select 字段
  - `_validation.py`（~110 行）：类型/状态/字段校验 mixin
  - `_suggestions.py`（~145 行）：自动推荐 mem_type / trigger_keywords mixin
  - `_search.py`（~570 行）：搜索/匹配/评分/cooldown/渲染 mixin
  - `_crud.py`（~420 行）：增删改查 mixin
- `shenyu_gateway/mem_notes_relevance.py`：~820 行纯函数，保持不变。
- `admin/src/views/Mem0View.vue`：仍是前端大文件，建议单独一轮处理，不要和后端核心重构混在一起。

这些数字不影响重构方向，但执行时不要按旧行号机械切文件。以函数名为准。

---

## 上下文拼接管线安全说明

上下文拼接管线由以下几个职责承载，本方案不改拼接语义：

```text
gateway.py::_prepare_messages() / prepare_messages.py::prepare_messages()
        编排器：trim → store → inject tool turns → build package → render → assemble
        ↓
context_builder.py::build_context_package()
        收集上下文源：calendar + heartbeat + mem_notes + stars
        ↓
context_layers.py::render_layered_additions()
        渲染各层文本：stable/slow/mem/heartbeat/format
        ↓
context_layers.py::assemble_layered_messages()
        将各层作为 system messages 插入消息列表 + bridge 消息
```

Phase 1.2 搬的是 `_prepare_messages()` 这个编排器本身。搬运后它调用的 `build_context_package`、`render_layered_additions`、`assemble_layered_messages` 等函数仍保持原语义。

---

## 修订摘要

1. Phase 1 是值得优先做的：`gateway.py` 应该回到 app 初始化、路由注册、生命周期和少量 runtime wiring。
2. `_stream_chat()` 不建议继续塞进 `streaming.py`。当前 `streaming.py` 已经承载内部 tool-loop 流式辅助，再放 300 行直连上游转发会把另一个文件养大。建议新建 `shenyu_gateway/stream_proxy.py`。
3. `_prepare_messages()` 的依赖比旧计划表格多。建议用 `PrepareMessagesDeps` dataclass 注入，避免十几个参数铺在函数签名上。
4. `_connect_error_detail` 来源修正：当前实际来自 `shenyu_gateway.upstream_client.connect_error_detail`，不是 `upstream_adapter`，且需要 `cfg`。搬迁时应传入 callable 或传入 `cfg`。
5. `tool_registry.py` 拆 schema 是对的，但 schema 文件只放纯 JSON schema builder。feature flag、surface 过滤、broker 选择、execute handler 都留在 registry。
6. `mem_notes.py` 拆匹配/评分逻辑是对的，但不要搬 DB select 字段。新文件建议叫 `mem_notes_relevance.py` 或 `mem_notes_scoring.py`，不要用 wildcard import。
7. `MEM_NOTE_PATCH_KEYS` 合并风险低，可以提前做，避免常量继续重复。

---

## Phase 0：低风险常量去重（P0.5，可先做）

### Step 0.1：合并 `MEM_NOTE_PATCH_KEYS`

**当前问题**：

- `tool_registry.py` 有 `MEM_NOTE_PATCH_KEYS`
- `mem_notes.py` 有 `MEM_NOTE_PATCH_FIELDS`
- 两者语义相同，后续如果只改一边会产生隐性 bug

**怎么做**：

1. 删除 `tool_registry.py` 内部的 `MEM_NOTE_PATCH_KEYS` 字面量。
2. 改为：

   ```python
   from shenyu_gateway.mem_notes import MEM_NOTE_PATCH_FIELDS as MEM_NOTE_PATCH_KEYS
   ```

3. 保持 `_mem_note_bulk_patch_arg()` 和 handler 逻辑不变。

**验证**：

```powershell
python -m py_compile shenyu_gateway\tool_registry.py shenyu_gateway\mem_notes.py
pytest tests/test_gateway_tool_registry.py tests/test_mem_notes.py
```

---

## Phase 1：拆 `gateway.py`（P0，优先级最高）

目标：把 `gateway.py` 降到约 550～650 行，只保留：

- 配置初始化
- runtime 对象初始化
- app / middleware / router 注册
- lifespan
- 少量闭包 wrapper，用于把 `cfg`、store、supabase 等 runtime 对象注入下游

### Step 1.1：提取 `_stream_chat()` → `shenyu_gateway/stream_proxy.py`

**搬什么**：

- `gateway.py::_stream_chat()` 整体。

**为什么不放进 `streaming.py`**：

当前 `streaming.py` 已经有底层 SSE helper、`StreamReplayAccumulator`、`read_next_stream_chunk()` 等内部 tool-loop 流式辅助。如果把 `_stream_chat()` 再搬进去，`streaming.py` 会变成新的大杂烩。`_stream_chat()` 的职责更像“直连上游流式代理”，单独放 `stream_proxy.py` 更清晰。

**建议新函数签名**：

```python
async def stream_chat(
    request: Request,
    payload: dict,
    headers: dict,
    model: str,
    upstream: dict,
    *,
    connect_error_detail: Callable[[str, Exception], str],
    private_capture_fallback_text: Callable[..., tuple[str, str]],
    private_capture_kinds: Callable[..., list[str]],
    on_complete: Optional[Callable[..., None]] = None,
    latest_user_text: str = "",
) -> StreamingResponse:
```

**依赖修正**：

| 符号 | 当前真实来源 | 处理 |
|---|---|---|
| `AssistantTagFilter` | `shenyu_gateway.response_capture` | 直接 import |
| `clean_text_from_filter_source` | `shenyu_gateway.response_capture` | 直接 import |
| `_connect_error_detail` | `gateway.py` wrapper → `upstream_client.connect_error_detail(cfg=cfg)` | 作为 `connect_error_detail` callable 传入 |
| `_private_capture_fallback_text` | `private_capture.py` 经 `gateway.py` import | 作为 callable 传入 |
| `_private_capture_kinds` | `private_capture.py` 经 `gateway.py` import | 作为 callable 传入 |
| `_anthropic_to_openai_chunk` | `upstream_adapter.py` | 直接 import |
| `_anthropic_stop_reason_to_openai` | `upstream_adapter.py` | 直接 import |
| `_anthropic_tool_index_override` | `upstream_adapter.py` | 直接 import |
| `_anthropic_usage_to_openai` | `upstream_adapter.py` | 直接 import |
| `_new_stream_chunk_id` | `streaming.py` | 直接 import |
| `_now_ts` | `runtime.py` | 直接 import |
| `_stream_content_event` | `streaming.py` | 直接 import |
| `_sse_response` | `streaming.py` | 直接 import |
| `logger` | `runtime.py` | 直接 import |
| `httpx` / `json` | 第三方 / stdlib | 直接 import |

**`gateway.py` 保留薄 wrapper**：

```python
async def _stream_chat(request, payload, headers, model, upstream, on_complete=None, latest_user_text=""):
    from shenyu_gateway.stream_proxy import stream_chat

    return await stream_chat(
        request,
        payload,
        headers,
        model,
        upstream,
        connect_error_detail=_connect_error_detail,
        private_capture_fallback_text=_private_capture_fallback_text,
        private_capture_kinds=_private_capture_kinds,
        on_complete=on_complete,
        latest_user_text=latest_user_text,
    )
```

**不改什么**：

- heartbeat 过滤逻辑
- fallback 文案逻辑
- OpenAI / Anthropic 双协议分支
- `on_complete` 回调参数和行为
- SSE 输出格式

**验证**：

```powershell
python -m py_compile gateway.py shenyu_gateway\stream_proxy.py
pytest tests/test_gateway_streaming.py tests/test_response_capture.py tests/test_upstream_adapter_stream.py
python -c "from gateway import app"
```

---

### Step 1.2：提取 `_prepare_messages()` → `shenyu_gateway/prepare_messages.py`

**搬什么**：

- `gateway.py::_prepare_messages()` 整体。

**修订意见**：

旧计划说它只依赖少数几个对象，实际不够完整。这个函数还用到：

- request log phase 标记：`_mark_request_log_phase`
- 时间：`_iso_now`
- client/session 解析：`_client_name_from_request`、`_session_tag_from_request`
- `SessionManager`
- `GatewayToolService`
- `ChatArchiveService` / `archive_window_safely`
- trim 函数：`_trim_client_messages`、`_trim_client_extra_bundle_attachments`、`_trim_package_install_tool_results`、`_trim_client_image_blocks`
- message helper：`_latest_user_text`、`_non_system_message_count`
- pending gateway tool injection
- cold start snapshot
- runtime prune
- room mode 判断
- `assemble_layered_messages`
- `supabase_client`
- `cfg`

所以不要把函数签名写成十几个参数。建议引入 dataclass。

**建议结构**：

```python
@dataclass(frozen=True)
class PrepareMessagesDeps:
    cfg: Any
    store: GatewayStore
    supabase_client: Any
    context_builder_factory: Callable[..., ContextBuilder]
    client_name_from_request: Callable[[Request], str]
    session_tag_from_request: Callable[..., str]
    is_hisense_client: Callable[[Optional[str]], bool]
    upstream_for_hisense: Callable[[bool], dict]
    maybe_prepare_cold_start_snapshot: Callable[..., Optional[dict]]
    prune_runtime_state: Callable[[Optional[str]], dict[str, int]]
```

如果 import 类型会引入循环，`GatewayStore` / `ContextBuilder` 可放在 `TYPE_CHECKING` 中，运行时用 `Any`。

**建议新函数签名**：

```python
async def prepare_messages(
    request: Request,
    body: ChatRequest,
    deps: PrepareMessagesDeps,
) -> tuple[list[dict], dict]:
```

**`gateway.py` 保留薄 wrapper**：

```python
async def _prepare_messages(request: Request, body: ChatRequest) -> tuple[list[dict], dict]:
    from shenyu_gateway.prepare_messages import PrepareMessagesDeps, prepare_messages

    return await prepare_messages(
        request,
        body,
        PrepareMessagesDeps(
            cfg=cfg,
            store=_require_session_store(),
            supabase_client=supabase_client,
            context_builder_factory=_context_builder,
            client_name_from_request=_client_name_from_request,
            session_tag_from_request=_session_tag_from_request,
            is_hisense_client=_is_hisense_client,
            upstream_for_hisense=_upstream_for_hisense,
            maybe_prepare_cold_start_snapshot=_maybe_prepare_cold_start_snapshot,
            prune_runtime_state=_prune_runtime_state,
        ),
    )
```

**直接 import 的纯函数/模块**：

- `SessionManager`
- `GatewayToolService`
- `ChatArchiveService`
- `archive_window_safely`
- `assemble_layered_messages`
- trim 函数
- `is_room_mode`
- `inject_pending_gateway_tool_turns`
- request log helpers
- runtime `iso_now`

**不改什么**：

- context package 的构建逻辑
- layered system message 的插入顺序
- room mode 分支行为
- cold start 行为
- 返回 meta dict 的 key 和结构

**验证**：

```powershell
python -m py_compile gateway.py shenyu_gateway\prepare_messages.py
pytest tests/test_gateway.py tests/test_gateway_streaming.py tests/test_gateway_hisense_context.py
python -c "from gateway import app"
```

---

### Step 1.3：提取中间件 → `shenyu_gateway/middleware.py`

**搬什么**：

- `_global_exc_handler()`
- `log_unhandled_exceptions()`
- `admin_auth_middleware()`

**建议结构**：

```python
def register_middlewares(app: FastAPI, cfg: Any) -> None:
    @app.exception_handler(Exception)
    async def _global_exc_handler(request: Request, exc: Exception):
        ...

    @app.middleware("http")
    async def log_unhandled_exceptions(request: Request, call_next):
        ...

    @app.middleware("http")
    async def admin_auth_middleware(request: Request, call_next):
        ...
```

**依赖处理**：

- `logger`、`iso_now` 从 `runtime.py` import
- `_start_http_request_event` / `_finish_http_request_event` 从 `request_logs.py` import
- `admin_auth_middleware_handler` 在函数内或文件顶层从 `auth.py` import
- `DEBUG_TRACEBACKS` 仍读环境变量

**注意**：

`register_middlewares(app, cfg)` 必须在 `app = FastAPI(...)` 后、路由注册前调用，保持行为接近原顺序。

**验证**：

```powershell
python -m py_compile gateway.py shenyu_gateway\middleware.py
pytest tests/test_gateway.py tests/test_gateway_streaming.py
python -c "from gateway import app"
```

---

## Phase 2：拆 `tool_registry.py`（P1）

目标：把纯工具 JSON schema 从 registry 中拿出去，让 `tool_registry.py` 专注：

- 工具 surface / feature flag 判断
- client tools 合并
- gateway native tool 判断
- broker 工具选择
- 参数解析
- tool handler / execute

### Step 2.1：提取工具 Schema → `shenyu_gateway/tool_schemas.py`

**搬什么**：

- `_gateway_list_mem_notes_tool()`
- `_gateway_core_tools()`
- `_gateway_mem0_management_tools()`
- `_gateway_notebook_and_recall_tools()`
- Supabase 工具 schema 建议从 `_expanded_gateway_native_tools()` 的 inline list 提成 `_gateway_supabase_tools()`

**不搬什么**：

- `_gateway_tool_surface()`
- `_filter_gateway_tools_for_surface()`
- `_filter_client_tools_for_surface()`
- `_expanded_gateway_native_tools()`
- `_gateway_tool_names()`
- `_gateway_broker_tool()`
- `gateway_native_tools()`
- `merge_tools()`
- `is_gateway_native_tool()`
- `ToolContext`
- `_TOOL_HANDLERS`
- `execute_gateway_tool()`
- 参数解析 helper：`_int_arg()`、`_bool_arg()`、`_query_arg()` 等
- `DAILY_GATEWAY_TOOL_NAMES` 等 surface 常量

**重要约束**：

- 不要 `from .tool_schemas import *`
- 用显式 import：

  ```python
  from .tool_schemas import (
      gateway_core_tools,
      gateway_list_mem_notes_tool,
      gateway_mem0_management_tools,
      gateway_notebook_and_recall_tools,
      gateway_supabase_tools,
  )
  ```

- 新文件里的函数可以去掉 `_` 前缀，也可以保留。若保留 `_` 前缀，导入时显式导入即可。
- schema 函数需要的 enum 从 `mem_notes.py` import：`MEM_NOTE_MEMORY_KINDS`、`MEM_NOTE_TYPES`。

**验证**：

```powershell
python -m py_compile shenyu_gateway\tool_registry.py shenyu_gateway\tool_schemas.py
pytest tests/test_gateway_tool_registry.py tests/test_gateway_tools_return_format.py tests/test_gateway_tools_notebook.py
```

---

## Phase 3：拆 `mem_notes.py`（P1）✅ 已完成

目标：让 `mem_notes.py` 主要保留 `MemNoteService` 和 DB/service 层逻辑，把匹配、评分、清洗等纯函数拿出去。

> **Status**: Step 3.1（relevance 纯函数提取）和 Step 3.2（mixin 包拆分）均已完成。
> `mem_notes.py` 已删除，替换为 `mem_notes/` 包。39/39 测试通过，所有外部 import 向后兼容。

### Step 3.1：提取匹配/评分逻辑 → `shenyu_gateway/mem_notes_relevance.py` ✅

**推荐文件名**：

- 首选：`mem_notes_relevance.py`
- 可选：`mem_notes_scoring.py`
- 不建议：`mem_notes_match.py`，因为里面不只是 match，还有 query 清洗、semantic signal、serendipity rate 等 relevance 逻辑。

**搬什么**：

- regex / 常量：
  - `_CONTEXT_QUERY_ATTACHMENT_RE`
  - `_PROXY_SENDER_RE`
  - `_TOOL_RESULT_BLOCK_RE`
  - `_CODE_BLOCK_RE`
  - `_JSON_LIKE_BLOCK_RE`
  - `_URL_RE`
  - `_TRIGGER_KEYWORD_JUNK_TOKENS`
  - `CONTEXT_KEYWORD_MIN_SCORE`
  - `CONTEXT_SEMANTIC_MIN_SCORE`
  - `CONTEXT_SEMANTIC_MIN_VECTOR_SCORE`
  - `CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE`
  - `CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE`
  - `CONTEXT_WEAK_KEYWORD_HITS`
  - `AUTO_STRONG_TRIGGER_TERMS`
  - `CONTEXT_RELATION_NAME_TERMS`
  - `_COMMON_TRIGGER_TERMS`
  - `AUTO_TRIGGER_GENERIC_TERMS`
  - `CONTEXT_SEMANTIC_STRONG_TERMS`
  - `CONTEXT_SEMANTIC_ANCHOR_STOP_TERMS`
  - `_DERIVED_TRIGGER_STOP_TERMS`
  - `_SUGGESTION_SEED_KEYWORDS`
  - `_TRIGGER_KEYWORD_STOP_TERMS`
  - `_TRIGGER_PHRASE_SPLIT_RE`
  - `_ENTITY_NAME_PATTERN`
  - `_ENTITY_ENGLISH_NAME`
  - `_ENTITY_STOP_WORDS`
- 纯函数：
  - `_anchor_match()`
  - `_skip_auto_surface()`
  - `_overlap()`
  - `_trigger_unit_weight()`
  - `_should_derive_keyword_terms()`
  - `_trigger_units()`
  - `_trigger_overlap()`
  - `_clean_context_query()`
  - `_strip_tool_result_blocks()`
  - `_terms()`
  - `_has_non_word_symbol()`
  - `_generic_chinese_semantic_fragment()`
  - `_valid_semantic_anchor_term()`
  - `_semantic_anchor_hits()`
  - `_query_semantic_signal_terms()`
  - `_low_information_semantic_query()`
  - `_auto_extract_entities()`
  - `running_joke_serendipity_rate()`

**建议留在 `mem_notes.py`**：

- `MEM_NOTE_TYPES`
- `MEM_NOTE_STATUSES`
- `MEM_NOTE_MEMORY_KINDS`
- `MEM_NOTE_PATCH_FIELDS`
- `MEM_NOTE_BULK_UPDATE_MAX`
- `_UUID_RE`
- `_normalize_note_id()`
- `_MEM_NOTE_SELECT_FIELDS`
- `_MEM_NOTE_SELECT_FIELDS_LIGHT`
- `class MemNoteService`

原因：

- select fields 是 DB/service 层，不属于 relevance。
- `_normalize_note_id()` 是 service 参数规范化，和 DB 操作绑定更近。
- 公共常量继续从 `mem_notes.py` 暴露，避免外部 import 断裂。

**import 约束**：

- 不要 wildcard import。
- `mem_notes.py` 显式导入需要的名字：

  ```python
  from .mem_notes_relevance import (
      CONTEXT_KEYWORD_MIN_SCORE,
      CONTEXT_SEMANTIC_MIN_SCORE,
      ...
      _clean_context_query,
      _skip_auto_surface,
      ...
      running_joke_serendipity_rate,
  )
  ```

- 继续让旧外部 import 可用。当前测试有：

  ```python
  from shenyu_gateway.mem_notes import MemNoteService, _clean_context_query
  from shenyu_gateway.mem_notes import running_joke_serendipity_rate
  ```

  所以 `mem_notes.py` 中必须 re-export 这些名字，不能只搬走不导入回来。

**验证**：

```powershell
python -m py_compile shenyu_gateway\mem_notes.py shenyu_gateway\mem_notes_relevance.py
pytest tests/test_mem_notes.py tests/test_gateway_tool_registry.py
```

---

## Phase 4：清理 `gateway.py` wrapper 噪音（P2）

Phase 1 完成后再判断，不急着做。

当前 `gateway.py` 有不少类似：

```python
def _foo(arg):
    return _foo_impl(arg, cfg=cfg)
```

这些 wrapper 虽然机械，但它们承担 runtime wiring。优先级低于 Phase 1～3。

后续可以考虑：

- 把 upstream runtime wiring 收到一个 `GatewayRuntimeDeps` 或 `RuntimeWiring` dataclass。
- 或者把 router deps 构造拆到 `route_wiring.py`。

不要在第一轮大规模消除 wrapper，避免同时改变太多调用边界。

---

## Phase 5：前端 Vue 拆组件（P2，单独一轮）

### Step 5.1：拆 `admin/src/views/Mem0View.vue`

建议另开一轮，不要和后端核心重构同 commit。

**可拆出**：

- `Mem0Table.vue`：表格 + 排序/分页
- `Mem0FilterBar.vue`：筛选器区域
- `Mem0EditDialog.vue`：编辑弹窗
- `Mem0BulkActions.vue`：批量操作栏

父组件 `Mem0View.vue` 只负责：

- 拉取数据
- 状态管理
- 调用 API
- 组合子组件

目标：父组件降到约 300～450 行。

**验证**：

```powershell
cd admin
npm test -- --run
npm run build
```

如果没有 test script，则至少跑：

```powershell
cd admin
npm run build
```

---

## 推荐执行顺序

```text
Phase 0.1  常量去重
    ↓
Phase 1.1  stream_proxy.py
    ↓
Phase 1.2  prepare_messages.py
    ↓
Phase 1.3  middleware.py
    ↓
Phase 2.1  tool_schemas.py
    ↓
Phase 3.1  mem_notes_relevance.py
    ↓
Phase 4    wrapper 清理（可选）
    ↓
Phase 5    前端拆组件（单独一轮）
```

如果想更保守，也可以先做 Phase 1.3 中间件拆分，因为它最独立。

---

## 每步检查清单

每一步都要确认：

- [ ] `python -m py_compile` 覆盖本步改过的 Python 文件。
- [ ] 对应 pytest 通过。
- [ ] `python -c "from gateway import app"` 不报错。
- [ ] `git diff` 中除了 import、函数位置、依赖注入外，没有业务逻辑变化。
- [ ] 没有 `from module import *`。
- [ ] 没有引入新的 import cycle。
- [ ] 中文文件仍是 UTF-8。
- [ ] 如果改过中文文本，扫描常见 mojibake：`淇`, `閺`, `鈹`, `銆`, `锛`, `紝`, `娌堜簣`。

建议最终全量跑：

```powershell
python -m py_compile gateway.py shenyu_gateway\*.py
pytest
python -c "from gateway import app"
```

---

## Claude 执行注意事项

1. 不要按旧行号搬，按函数名搬。
2. 每个 phase 单独 commit 或至少单独检查 diff。
3. 重构中不要顺手改业务逻辑、文案、fallback 行为、prompt 内容、上下文层顺序。
4. 对 `gateway.py` 的 wrapper 保留是可以接受的，第一目标是降低主文件体积和职责混杂。
5. 如果遇到 import cycle，优先用依赖注入/dataclass 解决，不要把 runtime 全局对象从 `gateway.py` 反向 import 到子模块。
6. `prepare_messages.py`、`stream_proxy.py` 这两个新边界最关键：前者是上下文准备编排，后者是直连上游流式代理。不要让它们互相 import。
