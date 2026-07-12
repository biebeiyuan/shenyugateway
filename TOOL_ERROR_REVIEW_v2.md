# 工具报错分类 / broker schema 收敛 —— 审查结论（修正版 v2）

> 本版在原审查基础上，把每条说法拉到真实代码逐行核对后修正。核对方式：静态对照 + 测试↔实现三角验证 + 直接读取工作区/index 字节。测试仍需你实跑：
> `python -m pytest tests/test_gateway_tool_registry.py tests/test_gateway_store.py`

---

## 分级总表

| 级别 | 条目 | 结论 | 要不要动 |
|---|---|---|---|
| 🔴 | ~56 文件 CRLF 行尾污染 | **成立且仍活**（WSL/autocrlf=false 提交路径会 churn） | 根治：加 `.gitattributes`，与设计改动分两个提交 |
| 🟡 | broker 拒废弃工具无 error_kind/redirect，与 direct 不对称 | **成立**（增强，非设计违规） | 建议修 |
| 🟢 | 分类函数多了异常启发式（实现对、文档旧） | **成立** | 同步文档；另有假阳性边 |
| 🟢 | ~~第二步"不改什么"与拍板#3 自相矛盾~~ | **撤销：文档并不矛盾，原判为误判** | 无需动 |
| 🟢 | service 层三方法成分发死代码 | **成立** | 后续清理 |
| 🟢 | `?kind=` 链路通但前端没用 | **成立** | 可留 |
| ✅ | "确认正确"区 (a)–(f) | **六点全对** | — |

---

## 🔴 严重：CRLF 行尾污染（成立，且是根因问题）

**核实到的字节级事实：**
- `git ls-files --eol`：`gateway_tools.py`=`w/crlf`、`config.py`=`w/crlf`、`runtime.py`=`w/mixed` → 工作区这些文件**此刻确实是 CRLF/混合**，污染仍在。
- index blob 是纯 LF（`git cat-file -p :file` 计 CRLF=0）。
- 仓库**没有 `.gitattributes`**，`.git/config` 也没设 `core.autocrlf`。

**关键澄清（原审查漏掉的一层）：churn 是否发生，取决于用哪个 git 提交。**
- **WSL 原生 git**（Linux 默认 `autocrlf=false`）：CRLF 工作区 ≠ LF index → `git diff` 显示这 ~56 文件为改动 → 提交产生 `+N/−N` 纯行尾 churn、毁 blame。**这是真实风险，也是审查员当时看到 ~67 文件的原因。**
- **Windows 侧 git**（`autocrlf=true`，来自 Git 安装的系统配置）：提交时把 CRLF 规范化回 LF → 这些文件不进 diff → 干净 12 文件提交。

因此这不是"一次性夹带"，而是**缺 `.gitattributes` + autocrlf 客户端相关**造成的系统性隐患：只要 Windows / WSL / Codex 三方来回操作，就会反复复发。

**根治（首选，客户端无关）：**
1. 新增 `.gitattributes`：`* text=auto` + 源码 `eol=lf`。
2. 在 WSL 里 `git add --renormalize .`，**单独成一个提交**。
3. 设计改动（下述 11 文件）**另成一个提交**，两者绝不混。

逐文件 `git checkout -- <file>` 只是创可贴，且在 autocrlf=true 的客户端上 checkout 会再 smudge 回 CRLF，治标不治本。

---

## 🟡 中：broker 与 direct 拒绝废弃工具不对称（成立，属增强）

三个废弃工具 `shenyu_ask_memory` / `shenyu_search_primary_texts` / **`shenyu_get_meta_summaries`**（注意第三个名字带 `get_`）：

- **direct 路径**（`tool_registry.py:875-876`）：返回 `DEPRECATED_COMPAT_TOOL_MESSAGES[name]`，带 `error_kind="validation"`，消息含 "Use shenyu_recall instead."
- **broker 路径**（`tool_registry.py:820-828`）：名字不在 allow-list → 落到通用 `"Unsupported gateway broker target: <name>. Use tool with the full shenyu_/supabase_ name, and put arguments in params."`，**无 error_kind、无 recall 重定向**。

两条最终都会被判成 validation（broker 靠启发式兜底），落库分类没问题；但给沈予的引导不对称。**注意：文档只要求 direct handler 明确拒绝，并未要求 broker 对称**，所以这是"值得做的增强"而非设计违规。

**建议改法**：在 `tool_registry.py:820` 那句 `if target_name not in allowed:` 之前插入
```python
if target_name in DEPRECATED_COMPAT_TOOL_MESSAGES:
    return {"ok": False, "error": DEPRECATED_COMPAT_TOOL_MESSAGES[target_name], "error_kind": "validation"}
```
并同步守护测试 `test_execute_gateway_tool_rejects_hidden_ask_memory_broker_target`（它当前锁死 "Unsupported gateway broker target" 这句）。

---

## 🟢 低

### 1. 分类函数多了异常启发式（实现对、文档旧）—— 成立
`_classify_tool_error`（`tool_loop.py:640-659`）在 config 短语之后、validation 之前多了一档 `exception_markers`（traceback / exception / attributeerror / typeerror / object has no attribute）。文档伪代码没这一档，但文档 1.4(c) 的 `'list' object has no attribute 'strip'` 要求归 exception——**照纯伪代码跑会落到 validation，文档自相矛盾，实现补对了**。测试 `test_classify_tool_error_uses_declared_kind_first` 也断言那条 == exception。建议把文档伪代码同步成实现，并注明"真异常主要靠 except 块显式写 `error_kind="exception"`（`tool_loop.py:205/603` 已做），启发式只是兜底"。

**补充（原审查未提）——假阳性边**：启发式是纯子串匹配且不区分大小写。
- validation 消息只要含子串 `exception`（如 `unknown tool: shenyu_exception_log`）会被误判成 exception。
- config 短语里的 `"not available"` 很泛，`"... not available"` 的真异常会先被吞成 config（config 在 exception 之前判）。

仅影响仪表盘归类、不影响行为，但值得记一笔。真异常因为走 except 块显式打标，不受此影响。

### 2. ~~第二步"不改什么"与拍板#3 自相矛盾~~ —— 撤销（原判为误判）
逐行核对文档：
- `:182` 的"不改 `execute_gateway_tool`"处于**第一步（分类步）**作用域内，正确。
- **第二步** `:210` / `:214` 明写"direct handler 也不再静默转发……会改的是……三个废弃直连 handler 的静默转发行为"，与 §7 拍板#3（`:307`）**一致**。

文档**不存在自相矛盾**。原审查把第一步的"不改"误当成第二步的全局声明。实现（`:875-876` 加了 direct 拒绝）按拍板正确——这条结论保留，但"文档打架"的说法删除。

### 3. service 层三方法成分发死代码 —— 成立
`gateway_tools.py:628/767/920`（`ask_memory` / `search_primary_texts` / `meta_summaries`）仍在，但 handler 删、broker 拒、direct 拒，分发路径到不了它们；`recall.py` 的 meta_summaries 走 supabase.query 直连。因 `test_gateway_tools_return_format.py` 仍直接测这三个方法，保留有测试依据。非违规，记一笔后续清理。

### 4. `?kind=` 链路通但前端没用 —— 成立
`list_tool_errors(kind=)`（`store/_admin.py:275`）、路由 `?kind=`（`gateway_admin_routes.py:60-63`）、`fetchToolErrors(limit, kind?)`（`toolErrors.ts:16`）都接好；但 `ToolErrorsView.vue:47` 的 `loadErrors()` 调 `fetchToolErrors(50)` 不传 kind，过滤全在 `visibleErrors` computed 里做客户端。50 条规模无碍。**补一点**：客户端的"真报错"=exception+config 并非单个 `kind` 值，真要接服务端过滤还得做一层映射。

---

## ✅ 确认正确（六点全核对通过）

- **(a) 迁移**：`store/_base.py:200` CREATE TABLE 有 `error_kind TEXT NOT NULL DEFAULT 'unknown'`；`:249-254` 用 `_ensure_column` 加列。后端是 **SQLite**（`sqlite3.Connection`），`ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT 'unknown'` 合法（SQLite 允许带常量 DEFAULT 的 NOT NULL 加列），`PRAGMA table_info` 判存在正确 → 老库零停机、旧行回填 'unknown'。
- **(b)** `log_tool_error` 加 `error_kind="unknown"` 默认参（`store/_admin.py:251`），不破老调用；`list_tool_errors` 加 kind 过滤（参数化查询，无注入）。**INSERT 为 10 列 / 10 占位 / 10 值，无 off-by-one。**
- **(c)** 两处 except 块都显式写 `error_kind="exception"`（`tool_loop.py:205` / `:603`），真异常不靠字符串猜。
- **(d)** `error_source` 保留并由 error_kind 派生（`tool_loop.py:667`：exception→"execute"，否则→"result"），新旧双写。
- **(e)** broker schema 只露 `tool`+`params`（`tool_registry.py:242-252`），`arguments` 属性已删，`required=["tool"]`；描述删了"省略前缀也行"。
- **(f)** 三个废弃工具名不泄露进 `tool_schemas.py` 的任何 enum（0 处）。

---

## 对原审查的总评

- **质量：高。** 行号精度极高（约 15 处引用全部准到 ±2 行），认知诚实（明确声明无法实跑并建议跑 pytest），善用测试↔实现三角验证。
- **逻辑：大体扎实，两处需修：**
  1. 🔴 根因判浅（当成一次性夹带，未识别"缺 .gitattributes + autocrlf 客户端相关"的系统性 + churn 的客户端依赖性）。
  2. green-3 误判（凭空造了个不存在的"文档自相矛盾"）。
- **漏点：** 未独立验证迁移的后端正确性（方向对）、未提分类器假阳性边、把第三个废弃工具名误写为 `shenyu_meta_summaries`（实为 `shenyu_get_meta_summaries`）。
