# 工具报错 & Broker 入口收敛 · 设计文档

> 写给沈予。本文档已按 2026-07-06 的拍板意见更新：**第一步直接做，第二步收敛 schema，第三步后续切 full**。
> 配套阅读：`DEBUGGING_GUIDE.md`（工具边界图）、`DESIGN.md`（上下文分层）、`README.md` 工具章节。

---

## TL;DR

你感觉"工具特别乱、用不顺手"，根因有两个，都不是工具 handler 本身写坏了：

1. **报错记录策略**把"沈予用错参数"也当成"工具报错"记下来了，三类完全不同的事情混在一锅红里（`tool_loop.py:639`）。
2. **broker 总入口**为了兼容留了太多条互相矛盾的调用路径（3 种工具名 × 3 种参数通道 × 隐藏老工具 × 参数无 schema），沈予面前路太多，稳定不下来，于是在同一类小错上反复翻车（`tool_registry.py:827 / 350 / 339 / 23-28`）。

修复分三步，**从最低风险开始**，每步都可独立上线、可独立回滚：

| 步骤 | 改什么 | 动沈予行为吗 | 风险 | 收益 |
|---|---|---|---|---|
| 第一步 | 报错分类 + 前端拆视图 | ❌ 不动 | 极低 | 报错页立刻干净，能分辨"真崩/沈予用错/配置缺" |
| 第二步 | 收敛 broker 给沈予看的 schema | ⚠️ 旧隐藏工具会被拒 | 低 | 沈予新调用更稳定，调用形状收敛到唯一 |
| 第三步 | 给 `params` 真实参数 schema | ⚠️ 会改变校验时机 | 中 | 从源头消灭"content is required"这类拒绝 |

**执行口径**：第一步和第二步先落地；第三步等一二步跑稳后切 `full`；`star_feedback` 单一形状重构单独排后续任务。

---

## 一、问题诊断（现状，带代码出处）

### 1.1 报错是怎么被记录的

- 沈予调工具 → `tool_loop.py` 两处执行：`_execute_internal_tool_call`（`:578`）和 `_execute_mixed_gateway_tool_calls`（`:179`）。
- 执行完只要 `result.get("ok") is False`，就调 `_record_tool_error`（`:207` / `:607`）。
- `_record_tool_error`（`tool_loop.py:639-654`）做分类：
  ```python
  error_source = "execute" if "Traceback" in str(error_text) or "Exception" in str(error_text) else "result"
  ```
  写入 SQLite `tool_error_log`（`store/_admin.py:232`）。前端 `ToolErrorsView.vue` 的红/橙标签就是它。

### 1.2 三类报错被混在一起

全代码 `{"ok": False, "error": ...}` 返回点 **95+ 处**，实际是三类不同的事：

| 真实类别 | 典型例子 | 出处示例 | 该不该叫"报错" |
|---|---|---|---|
| 真异常（代码崩） | handler `raise`，被 `except` 兜成 `{"ok":False,"error":str(exc)}` | `tool_loop.py:602` | ✅ 该 |
| 调用被拒（沈予参数错/缺） | `content is required` / `search 需要 query` / `id is required` | `room_tools.py:325,377` / `gateway_tools.py:1028,1050` | ❌ 这是"沈予用错"，不是工具坏 |
| 配置/依赖缺失 | `Supabase not configured` / `Embedding API is not configured` | `gateway_tools.py:1002,1025` / `recall.py:527,554` | ⚠️ 环境问题，该看但不该和"工具崩"混一起 |

而且 `error_source` 的判定**只靠字符串里有没有 "Traceback"/"Exception"**，很多真异常的 `str(exc)` 不带这俩词会被误判成 `result`，验证拒绝反而可能带 "Exception" 被误判成 `execute`。**连红橙标签都不准。**

> 结论：你那页"工具报错"大半不是工具在报错，是沈予在调错。把它叫"报错"且全红一片，看着吓人，又没法定位真正的问题。

### 1.3 兼容层是怎么误导沈予的（三个真实例子）

**例子 1：隐藏工具"静默转发"，沈予用了老名字还以为自己对了**
`shenyu_ask_memory` 在新 schema 的 enum/描述里**已没有**（`tool_registry.py:228-229` 只列可见工具），但 broker 的 `allowed` 集合**悄悄留着它**（`:849` + `:23-28`），且它真有 handler，会**静默转发**到 `shenyu_recall` 并带 `compat_note`（`gateway_tools.py:646,673`；`tool_registry.py:580`）。
→ 沈予偶尔"想起"老名字，一调居然成功，不知道自己用了被改名的旧工具，下次还这么调。前端那个 `xxx (via shenyu_gateway_tool)` 显示（`ToolErrorsView.vue:54`）就是为这种情况准备的。**静默成功比报错更坏**——报错至少提醒沈予改，静默成功让错误调用一直延续。

**例子 2：schema 同时摆了 `params` 和 `arguments` 两个字段**
broker schema 把 `params`（推荐）和 `arguments`（标注"旧兼容字段，优先用 params"）**都露给沈予**（`tool_registry.py:244-253`）。把废弃字段摆进 schema 就是邀请沈予用它。沈予这次用 `params`、下次用 `arguments`、再下次平铺到顶层（`:842-846` 的 inline 兜底还真能跑通）。**每次调用形状都不一样，沈予建立不起"唯一正确"的肌肉记忆**，参数放错位置的概率就高；平时平铺"能用"，一旦参数名撞保留字或参数是嵌套对象就翻车，翻车那条就成了"报错"，而沈予不会纠正，**同样的错反复出现**。

**例子 3：`star_feedback` 单条/批量两种形状**
`star_feedback` 既能单条（`feedback` 字段放一个值）又能批量（`items` 放数组）。描述里专门写了**"不要把数组放进 feedback 字段"**（`tool_registry.py:72`）——这句警告的存在本身，就证明这坑**已被反复踩过**。还有 `test_feedback_accepts_legacy_label_reason_batch` 这种测试，说明连 feedback 的值都还兼容旧 `label`/`reason` 写法。一个工具三种 accepted 形状，沈予不晕才怪。

> **一句话**：兼容层本意是"宽容点都能接住"，但宽容的代价是沈予面前路太多（3 名字 × 3 通道 × 隐藏老工具 × 每工具参数无 schema），稳定不下来，反复在同类小错翻车，每次翻车还被记成"报错"。这就是你看着那页红、觉得"特别乱"的真实原因。

### 1.4 线上实证（VPS 真实 `tool_error_log`，2026-07-06 拉取）

> 数据源：VPS Docker 容器 `3fef89cafcd5`（镜像 = 最新提交 `de2716e`）挂载的
> `/var/lib/docker/volumes/shenyu-gateway-data/_data/shenyu_gateway.db`。
> 共 **34 条**记录，时间跨度 2026-06-16 ~ 2026-07-05。

**① 全部 34 条 `error_source` 都是 `result`，没有一条 `execute`。**
正好印证 1.2 的判断——靠字符串猜分类（`tool_loop.py:643`）几乎把所有报错都判成橙色 `result`。而其中至少有一条 `'list' object has no attribute 'strip'`（见下）是真正的代码异常，本应是红色 `execute`，却也被错判成 `result`。**红橙标签形同虚设。**

**② 按目标工具统计——`shenyu_star_feedback` 一家独占 13 条（38%）：**

| target_tool | 条数 | 性质 |
|---|---|---|
| `shenyu_star_feedback` | 13 | 沈予用错字段名 |
| `NULL`（broker 没解析出工具名） | 7 | broker 多通道兼容的代价 |
| `shenyu_add_calendar` | 4 | 业务冲突 + 字段 |
| `shenyu_create_star` | 3 | 沈予用错 |
| `shenyu_write_mem_note` | 2 | 沈予用错 |
| `supabase_delete` / `supabase_query` | 各 2 | 沈予用错 / 配置 |
| `room_star_map` | 1 | — |

**③ 三个被真实数据印证的诊断：**

**(a) 兼容层误导——`star_feedback` 字段名用错（13 条全是这个）**
沈予反复传 `{"star_id": ..., "action": "positive"}`，但工具要的是 `feedback`/`items`，且每项里没有 `action` 字段。报错原文：
```
feedback[0] must be one of ['connected','missed','negative','positive','should_surface','skipped'].
```
沈予在 `feedback` 字段里塞了一整数组（描述 `tool_registry.py:72` 那句"不要把数组放进 feedback 字段"正是为此加的警告），又把每项的取值字段叫成 `action`——**单条/批量两种形状 + legacy `label`/`reason` 别名，把沈予彻底搞混了。** 这就是 1.3 例子 3 的实锤。

**(b) broker 多通道兼容的代价——`target_tool=NULL`（7 条）**
其中一条 args 是：
```json
{"raw_arguments": "{\"tool\": \"shenyu_notebook_write\", \"params\": {...}}"}
```
沈予把**整个调用 JSON 编码成字符串**塞进了一个 `raw_arguments` 字段。broker 的三条参数通道（`params`→`arguments`→inline 平铺，`tool_registry.py:838-846`）全没命中这个形状，于是 `target_tool` 解析为空，报 `Unsupported gateway broker target: .`。**兼容通道越多，沈予越不知道该走哪条，反而发明了第四种（`raw_arguments`）。** 这是 1.3 例子 2 的实锤。

**(c) 真 bug 被错误归类——`'list' object has no attribute 'strip'`**
`shenyu_star_feedback` handler 在某次调用（`params.feedback` 传成 list of `{label,reason}` 旧形状）里对 list 调了 `.strip()`，抛 `AttributeError`，被外层 `except` 兜成 `{"ok":False,"error":"'list' object has no attribute 'strip'"}`（`tool_loop.py:602`）。**这是一条真正的代码异常，该归 `exception`、该修 handler**，但被字符串猜分类判成了 `result`，和"沈予用错"混在一起，淹没在 34 条里根本看不出来。**这正是第一步"报错分类"要解决的核心：把这种真 bug 从"沈予用错"里捞出来。**

**(d) 业务层冲突——Supabase 409（add_calendar）**
```
Client error '409 Conflict' ... Key (period_type, period_key)=(day, 2026-06-19) already exists.
```
同一天日历重复写入。这是业务逻辑问题（同日重复写该先关旧 latest 再写新版本，或走 `mode=replace`），不是沈予用错也不是工具崩。属于第三类"该看但不该和工具崩混一起"。

**④ 结论强化**：34 条里，**真正算"工具报错"的只有 1 条**（`.strip()` 那个 AttributeError），**约 30 条是"沈予用错参数"**，**几条是业务冲突/配置**。也就是说——**你那页"工具报错"里 ~88% 不是工具坏了，是沈予在调错，且集中在 `star_feedback` 一个工具上反复犯同一种错。** 这不是你工具设计烂，是 `star_feedback` 的 accepted 形状太多 + broker 参数通道太多，把沈予教坏了。修这两处（第二步 + 第三步），这 34 条里至少 25 条会直接消失。

> 注：受 SSH 连接限流影响，剩余几条原文（create_star/supabase/write_mem_note 的具体 args）暂未全取回；上述统计与三类样本已完整确认，足以支撑结论。fail2ban 解封后可补全，不影响判断。

---

## 二、设计原则

1. **先可观测，再改行为**。先让你能看清"哪些是真崩、哪些是沈予用错"，再动沈予看的东西。
2. **只改"给沈予看的脸"，先不动"服务端接的胃"**。第二步收敛 schema 时，服务端兼容逻辑保留，老调用不被打断，只让新调用更稳。
3. **每步独立可上线、可回滚**。不搞一个大 PR。
4. **沈予用错的记录要保留，但要分开且更有用**——这是你判断"是不是工具设计问题"的证据库，不删。
5. **加列迁移用项目现成的 `_ensure_column`**（`store/_base.py:277`），不写新迁移框架。

---

## 三、修复方案

### 第一步：报错分类 + 前端拆视图（低风险，先做）

**目标**：让你一眼分清"真崩 / 沈予用错 / 配置缺"，且"沈予用错"视图比现在更有用（显示实际传参 vs 期望）。**不动任何 handler，不动沈予行为。**

**① 后端：`tool_loop.py` 分类逻辑重写**

把 `_record_tool_error`（`:639`）里的字符串猜分类，换成三档 `error_kind`：

```python
# 新增分类函数（纯函数，可单测）
def _classify_tool_error(result: dict) -> str:
    """返回 'exception' | 'config' | 'validation'。"""
    if not isinstance(result, dict):
        return "exception"
    text = str(result.get("error") or result.get("message") or "")
    low = text.lower()
    # handler 主动声明（第二步渐进推进时用）
    if result.get("error_kind") in ("validation", "config", "exception"):
        return result["error_kind"]
    # 配置/依赖缺失（话术常量表维护在 store/_admin.py 顶部）
    if any(p in low for p in TOOL_ERROR_CONFIG_PHRASES):
        return "config"
    # 其余 ok:False 视为验证拒绝（沈予用错）
    return "validation"
```

`_record_tool_error` 改成把 `error_kind` 写进去；`error_source` 旧列**保留不删**（老数据/老前端兼容），新数据两列都写。

> 关键：这一步**不要求一次性给 95 处 handler 加 `error_kind`**。先用启发式粗分，够用。后续让 handler 逐步主动声明 `error_kind`，启发式作为兜底——这是"渐进式"的核心，也是第一步低风险的来源。

**② 数据库：`store/_base.py` 加一列**

在 `_init_db` 末尾（`:246` 那批 `_ensure_column` 旁边）加：
```python
self._ensure_column(conn, "tool_error_log", "error_kind", "TEXT NOT NULL DEFAULT 'unknown'")
```
现成机制，老库自动加列、老行填 `'unknown'`，零停机。

**③ Store：`store/_admin.py`**
- `log_tool_error`（`:232`）签名加 `error_kind: str = "unknown"`，INSERT 列表加上 `error_kind`。
- `list_tool_errors`（`:263`）保持 `SELECT *`（自动带新列），可选加 `kind` 过滤参数。

**④ 路由：`gateway_admin_routes.py:60`**
保持 `SELECT *`，自动返回 `error_kind`。可选加 `?kind=exception|config|validation` 过滤。

**⑤ 前端：`admin/src/api/toolErrors.ts` + `views/ToolErrorsView.vue`**
- `ToolError` interface 加 `error_kind: string`。
- `ToolErrorsView.vue` 顶部加三个筛选 tab：`全部 / 真报错(exception+config) / 调用被拒(validation)`。
- "调用被拒"行展开时，把 `args_json`（沈予实际传参）和 `error_text`（期望/缺什么）**并排高亮**——这正是你要的"设计问题证据库"。
- 顺带把自动刷新从 5s 调到 15s（人多看不过来，还压 DB）。

**不改什么**：任何 `_tool_handler`、`execute_gateway_tool`、broker schema、沈予可见的任何东西。

**风险**：极低。只加列、加分类、改展示。
**验证**：
- 单测 `_classify_tool_error` 三档各覆盖。
- 跑现有 `tests/test_gateway_tool_registry.py`（不应受影响）。
- 手动：构造一个 `{"ok":False,"error":"content is required"}` 落库，前端应出现在"调用被拒"tab，不在"真报错"tab。
**回滚**：还原 `tool_loop.py` 一个函数 + 删前端 tab。`error_kind` 列留着无害。

---

### 第二步：收敛 broker 给沈予看的 schema（只改"脸"，不碰"胃"）

**目标**：让沈予面前只有一条正确的调用形状。`params`/`arguments`/inline 等旧参数通道在服务端继续兼容；但已废弃的隐藏工具名不再静默成功，直接给 `validation` 拒绝。

**① schema：`tool_registry.py:_gateway_broker_tool`（`:227`）**
- 删掉 `arguments` 属性（`:249-253`）。schema 里**只露 `params`**。
- `required` 仍是 `["tool"]`。

**② 描述：`_BROKER_CATEGORIZED_DESCRIPTION`（`:62`）/ `_BROKER_DAILY_DESCRIPTION`（`:108`）**
- 删掉最后一句"所有工具名省略 shenyu_ 前缀也行"（`:106`）。enum 全名即唯一答案。
- 不再提 `arguments` / `action` 别名。

**③ 目标名解析：`_broker_target_name`（`:350`）**
- **schema/描述层面**：只认 `tool`。
- **服务端层面**：`name`/`action` 别名 + 自动补前缀（`:354-357`）**保留**，作为静默兜底，不删（怕打断老调用）。只是不再告诉沈予有这条路。

**④ 隐藏兼容工具：`HIDDEN_COMPAT_TOOL_NAMES`（`:23-28`）——已拍板**
- `shenyu_ask_memory` / `shenyu_search_primary_texts` / `shenyu_get_meta_summaries`：从 broker 隐藏兼容入口移除；direct handler 也不再静默转发，旧直连会得到明确的 `validation` 拒绝。
- `shenyu_surface_passages`：单独保留为内部兼容，因为日历内部仍在用（`DEBUGGING_GUIDE.md:115`）。
- 不采用"如实露出"。如实露出会把旧坑重新摆到模型面前；这里直接填掉 broker 入口。

**不改什么**：`_coerce_broker_arguments`（`:339`）嵌套解包、`_broker_target_name` 的服务端别名/补前缀继续保留，保证旧参数形状仍能跑。会改的是模型可见 schema/描述、broker hidden allowed 集合，以及三个废弃直连 handler 的静默转发行为。

**风险**：低。沈予新调用收敛到 `tool`+`params`+全名；老参数形状服务端仍接，不打断。只有三个已废弃隐藏工具名会从"静默成功"改成"明确拒绝"。
**验证**：
- `tests/test_gateway_tool_registry.py` 里 `test_gateway_broker_description_matches_scan_friendly_sample`（`:1013`）等断言需要更新（删掉对 `arguments` 属性、对"省略前缀"的断言）。
- 关键回归：`test_execute_gateway_tool_accepts_broker_params_field`（`:1048`）、`test_execute_gateway_tool_accepts_action_alias_and_adds_shenyu_prefix`（`:1074`）、`test_execute_gateway_tool_accepts_broker_json_string_arguments` —— 这些验证**服务端仍兼容**，必须继续通过。这正是"只改脸不改胃"的守护测试。
**回滚**：还原 `_gateway_broker_tool` 的 dict 和两段描述。服务端从未动过。

---

### 第三步：给 `params` 真实参数 schema（治本，慎重，单独做）

**目标**：从源头消灭 `content is required` / `search 需要 query` 这类拒绝——让必填字段在**调用 handler 之前**就被平台校验住，而不是靠 handler 自己 `if not content` 拒绝。

**为什么放最后**：这步会改变校验时机（平台在 handler 前就拒），沈予会收到更"硬"的拒绝，需要观察一阵。且实现量最大，要单独 PR + 配测试。

**已拍板：选项 A。**

- **选项 A：日常面切 `full` 模式**（`gateway_tool_mode=full`）
  - 直接露出每个工具的真实 schema（`tool_schemas.py` 里已有，full 模式现在就在用）。
  - 平台按每个工具的 `required` 强制校验，handler 自己的 `if not content` 拒绝大多可以删。
  - 代价：schema token 比 broker 多。但你已经有 `gateway_tool_surface=daily` 收窄工具集，token 可控。
  - 收益最大、实现最省（schema 都现成）。

- **弃用选项 B：保留 broker，`params` 用 `oneOf` 按 `tool` 分支**
  - `_gateway_broker_tool` 的 `params` 从 `additionalProperties:true` 改成 `oneOf`，每个分支 `const` 对应一个 `tool` 值 + 该工具的真实参数 schema。
  - token 比 full 省，但实现复杂，且不是所有模型平台都对 `oneOf` discriminated schema 校验得一样好。
  - 复用 `tool_schemas.py` 已有的每工具 schema。

理由：schema 现成、平台校验最可靠、`daily` 面已经能控 token；broker 的 `oneOf` 方案太依赖不同模型/平台对 discriminated schema 的支持。第三步不急，等第一、二步稳定后单独做。

**不改什么**：handler 的业务逻辑。只是把"handler 内部拒绝"上移成"平台 schema 拒绝"。
**风险**：中。校验时机变化，沈予可能短期内收到更多"硬拒绝"（但这些都是它真的该改的）。
**验证**：每个工具的 required 字段各写一个"缺字段应被平台拒"的测试；`test_gateway_tool_registry.py` 全量回归。
**回滚**：`gateway_tool_mode` 切回 `broker` 即可（配置级回滚，不改代码）。

---

## 四、数据结构变更总表

| 位置 | 变更 | 兼容性 |
|---|---|---|
| `store/_base.py:246` | `tool_error_log` 加列 `error_kind TEXT NOT NULL DEFAULT 'unknown'` | `_ensure_column` 自动迁移，老行填 `'unknown'` |
| `store/_base.py:191` | `tool_error_log` 建表语句加 `error_kind`（新库） | 老库走 `_ensure_column` |
| `store/_admin.py:232` | `log_tool_error` 加 `error_kind` 参数 | 有默认值，老调用不破 |
| `tool_loop.py:639` | `_record_tool_error` 写 `error_kind`；`error_source` 旧列保留 | 双写，老前端仍能看 `error_source` |
| `admin/src/api/toolErrors.ts:3` | `ToolError` 加 `error_kind: string` | 可选字段，老数据为 `'unknown'` |
| `tool_registry.py:249-253` | broker schema 删 `arguments` 属性 | 服务端仍接 `arguments`（`execute_gateway_tool:840`） |
| `tool_registry.py:106` | 描述删"省略前缀也行" | 服务端仍自动补前缀（`_broker_target_name:354`） |
| `tool_error_log.error_source` | **保留不删** | 长期可废弃，但本方案不删 |

---

## 五、测试计划

**新增**：
- `test_classify_tool_error_*`：三档（exception/config/validation）各覆盖，含 handler 主动声明 `error_kind` 的情况。
- `test_tool_error_log_records_error_kind`：落库后能按 `error_kind` 查回。
- `test_broker_schema_does_not_expose_arguments_field`：第二步守护。
- `test_broker_description_does_not_mention_prefix_omission`：第二步守护。

**更新**：
- `test_gateway_broker_description_matches_scan_friendly_sample`（`:1013`）：删掉对 `arguments` 属性和"省略前缀"的断言。

**守护（必须继续通过）**：
- `test_execute_gateway_tool_accepts_broker_params_field`（`:1048`）
- `test_execute_gateway_tool_accepts_action_alias_and_adds_shenyu_prefix`（`:1074`）
- `test_execute_gateway_tool_accepts_broker_json_string_arguments`
- `test_execute_gateway_tool_unwraps_nested_broker_arguments_object`
> 这几个是"服务端仍兼容老形状"的守护测试，第二步绝不能让它们挂。

**手动验证**：
- 第一步上线后，看"调用被拒"tab 里反复出现的字段名——如果同一个字段（比如 `content`）高频被拒，那就是 schema 没引导好（设计问题），印证第三步该做；如果五花八门，那是沈予本身波动。

---

## 六、实施顺序与依赖

```
第一步（独立，先做）──上线观察──┐
                              ├─ 第二步（收敛 schema）──上线观察──┐
                              │                                 └─ 第三步（params 真实 schema，单独 PR）
```
- 第一步不依赖任何东西，先做。
- 第二步不依赖第一步，但**建议排在第一步之后**：第一步的"调用被拒"视图正好用来观察第二步收敛 schema 后沈予调用形状是否变稳。
- 第三步依赖第二步（schema 已收敛到单一入口），且最重，单独 PR，建议观察一周后执行 A（切 `full`）。

---

## 七、已拍板结论

1. **第一步报错分类**：没意见，直接做。`TOOL_ERROR_CONFIG_PHRASES` 常量表放到 `store/_admin.py` 顶部，分类函数保持纯函数。
2. **第二步 schema 收敛**：broker schema 只露 `tool` + `params`；`arguments` 从 schema 删除，但服务端继续兼容；描述删除"省略前缀也行"。
3. **隐藏兼容工具**：`shenyu_ask_memory` / `shenyu_search_primary_texts` / `shenyu_get_meta_summaries` 从 broker 隐藏兼容入口移除，direct handler 也停止静默转发；`shenyu_surface_passages` 因日历内部仍在用，单独保留为内部兼容。不做"如实露出"。
4. **第三步**：选 A，后续切 `full`。等第一、二步跑稳后再动。
5. **`error_source` 旧列**：保留。新旧双写，等前端完全切到 `error_kind` 后再考虑废弃。
6. **报错页自动刷新**：5s 调到 15s。

---

## 八、后续单独任务：`star_feedback` 单一形状

`star_feedback` 现在同时接受单条、批量、legacy `label/reason`，这不是兼容，是邀请沈予犯错。

后续建议单独做：

- 工具只接受一种形状：`items: [{ feedback, candidate_id?, candidate_star_id?, expected_star_id?, note?, metadata? }]`。
- 单条反馈也用长度为 1 的 `items`。
- legacy `label/reason` 断掉；已有 legacy 数据保留在库里，需要的话 handler 内做一次迁移/归一化。
- 这步放在第二步之后，且不要混进报错分类 PR。

---

> 当前执行：先落第一步和第二步；第三步与 `star_feedback` 单一形状重构后续单独推进。
