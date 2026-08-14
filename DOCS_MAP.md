# Shenyu Gateway 文档地图

这份文件回答两个问题：新线程应该先读什么，以及根目录里的 Markdown 分别是不是当前事实。项目规则尽量留在仓库中，避免只存在于某个模型的全局记忆里。

## 新线程入口

权威的最短顺序只有三步：

1. Coding agent 先遵守 `AGENTS.md`；Codex 自动加载它，Claude Code 自动加载根目录的 `CLAUDE.md` 并由它指过去，都不要求人额外阅读。
2. 人和 agent 都从 `START_HERE.md` 选择当前任务入口。
3. 只读该任务指向的现行专题文档和代码；不默认预读其他设计稿或 Debug 文档。

需要快速认识文件时，读 `README.md` § Maintenance Map 和 `docs/architecture/SYSTEM_ZONES.md`。需要判断一份 Markdown 是否仍是当前事实时，查本文件后续状态表。`DESIGN.md` 只在准备修改记忆或上下文内核时阅读相关章节；`DEBUGGING_GUIDE.md` 和 `LOGS_GUIDE.md` 都是按需参考。

## 内容归属

| 内容 | 主要文档 | 不应重复放置 |
|------|----------|--------------|
| 文件级模块清单（路径 + 一句话职责）的唯一正本 | `README.md` § Maintenance Map（由 `tests/test_project_map.py` 看守） | 其他文档不再自建顶层文件清单，只放指向正本的路标；保留的仅限本职视角的补充——`DESIGN.md` §12 的包内部子系统映射、`docs/architecture/SYSTEM_ZONES.md` 的分区核心文件（路径存在性同样被测试看守） |
| 项目入口、维护地图、配置、运行、部署 | `README.md` | 子系统完整设计和阶段性审计结论 |
| 请求、流式、工具、缓存、上下文、SQLite、归档 | `docs/architecture/REQUEST_CONTEXT.md` | README 长篇章节 |
| Mem、Stars、Room、private capture | `docs/architecture/MEMORY_ROOM.md` | README 或运维排障指南中的完整设计 |
| 全仓分区和跨区边界 | `docs/architecture/SYSTEM_ZONES.md` | 各专题文档重复文件清单 |
| 风险、证据、已确认修复、审计顺序 | `docs/architecture/AUDIT_MATRIX.md` | README 的临时 follow-up 计划 |
| 长期设计原则与语义不变量 | `DESIGN.md` | 实施日志和临时代码状态 |
| 故障排查命令与判断链 | `DEBUGGING_GUIDE.md` | 子系统完整说明 |
| 日志页面向日常使用的解释 | `LOGS_GUIDE.md` | 工程实现细节 |
| 历史方案、评审和已完成计划 | 对应设计稿或 `docs/history/` | 现行入口文档 |

## 现行文档

| 文档 | 职责 | 什么时候更新 |
|------|------|--------------|
| `AGENTS.md` | 跨 Codex、Claude Code、GLM 的项目工作规则 | 环境、协作方式、验证要求或排障入口改变时 |
| `CLAUDE.md` | Claude Code 自动加载的入口指针，只把 agent 指向 `AGENTS.md` | 几乎不动；只有 agent 入口文件的加载方式改变时 |
| `README.md` | 当前项目入口、架构和维护地图 | 模块、配置、API、部署或主要行为改变时 |
| `docs/architecture/SYSTEM_ZONES.md` | 现行代码分区、跨区桥梁和审计入口 | 模块责任、主要调用链或边界改变时 |
| `docs/architecture/AUDIT_MATRIX.md` | 分区风险、证据、测试缺口和审计顺序 | 风险被证实、排除、修复或测试覆盖改变时 |
| `docs/architecture/REQUEST_CONTEXT.md` | 请求、上下文、缓存、存储、归档和外部契约参考 | 这些子系统的现行行为改变时 |
| `docs/architecture/MEMORY_ROOM.md` | Mem、Stars、Room 和 private capture 参考 | 这些子系统的现行行为改变时 |
| `DESIGN.md` | 记忆、召回、上下文编排的长期原则和改动边界 | 核心语义或系统不变量改变时 |
| `DEBUGGING_GUIDE.md` | 当前请求链路、诊断方法和验证清单 | 日志字段、运维方式或排障路径改变时 |
| `LOGS_GUIDE.md` | 面向日常使用的日志页速查 | 日志页的含义、标签或展示方式改变时 |
| `docs/DELIVERY.md` | 全仓交付验收的唯一正本：四档状态梯、探针边界、验证基线与施工簿记法 | 交付状态档位、验收证据要求或探针边界改变时 |
| `docs/frontend/STYLE_AND_CRAFT.md` | admin 前端的 Agent 任务地图、风格基线、手感家法、出生清单和前端验收铁律 | 任务入口、配色、token、组件归属或前端验收方式改变时 |
| `DOCS_MAP.md` | 文档入口、职责和状态 | 新增、归档、改名文档或职责发生变化时 |

## 地图同步边界

地图不是每次改动都全部更新；按改变的事实找到唯一主入口：

| 发生的变化 | 必须核对 | 不需要做 |
|------|------|------|
| 修改了运行模块或独立维护的前端视图/面板 | `README.md` § Maintenance Map 是否能直接或通过 package 条目找到该路径；旧文件原本漏项也应在本次补上 | 不把每个 package mixin、私有 helper、测试或生成文件逐一展开 |
| 新增、删除、改名或移动上述独立边界 | 在同一次改动中更新 `README.md` § Maintenance Map | 不把完整设计说明塞回 README |
| 模块职责、主要调用链或跨区桥梁改变 | `docs/architecture/SYSTEM_ZONES.md` 和所属现行架构文档 | 纯内部优化且这些事实没变时，不制造文档改动 |
| 用户可见行为、配置、日志含义或排障方式改变 | 对应的现行专题文档、`DESIGN.md`、`LOGS_GUIDE.md` 或 `DEBUGGING_GUIDE.md` | 不因为“改了代码”就更新所有文档 |
| Markdown 新增、改名、归档或状态改变 | `DOCS_MAP.md` | 不登记不会进入仓库的临时调查笔记 |

`AGENTS.md` 负责要求 coding agent 在交付前执行这项核对；本节负责说明每类变化由哪张地图或现行文档承接。

## 证据等级

地图和审计工具回答的是不同问题，交付时按三种信号理解：

| 信号 | 当前检查 | 含义与处理 |
|------|----------|------------|
| 红灯：自动阻断 | Python 单测、Admin Playwright smoke、PWA Vitest 单测与构建、`tests/test_project_map.py` | 测试失败、浏览器运行时/同源资源失败或地图路径缺失时，先修复或明确解释，不能当作通过交付。 |
| 黄灯：人工复核提醒 | `python scripts/check_audit_freshness.py` | 只说明审计关联文件后来改过、正在修改或记录格式不完整；它不自动证明原审计结论失效，也不作为 CI 失败条件。 |
| Agent / 人工判断 | 对照代码、测试、日志和用户可见行为 | 判断文档语义是否仍准确、产品边界是否改变，以及是否需要更新审计结论；自动路径检查不能替代这个判断。 |

当前 CI 在 push 和 pull request 上运行 `pytest tests/ -x -q`，在 `admin/` 工作目录运行 `npm run test:e2e`，并在 `pwa/` 工作目录运行 `npm test`（Vitest 单测：历史来源优先级、handoff 去重、roll 变体、SSE 解析、时间线分组）和 `npm run build`（`vue-tsc` 类型检查 + Vite 构建）。Playwright smoke 负责页面可加载、核心交互、浏览器运行时错误和同源资源失败；它是活性护栏，不是视觉验收。

## 专题设计与实施记录

这些文件只在修改对应子系统时阅读。它们包含重要背景，但部分章节记录的是当时方案或实施过程，不能替代当前代码和现行文档。

| 文档 | 主题 | 使用方式 |
|------|------|----------|
| `STAR_RECALL_V2_DESIGN.md` | 星星召回和排序 | 修改 star ranker 时参考，并对照当前实现 |
| `MEM0_LIGHT_MEMORY_V2_DESIGN.md` | 轻记忆模型与实施记录 | 修改 mem notes 时参考，并对照 `DESIGN.md` |
| `PROMPT_CACHE_WINDOW_DESIGN.md` | 窗口、上下文岛和缓存断点 | 修改裁剪或 prompt cache 时重点阅读 |
| `PROMPT_CACHE_WINDOW_REVIEW.md` | 上述实现的一次审查快照 | 用于理解当时验收，不作为持续状态页 |
| `TOOL_ERROR_BROKER_REDESIGN.md` | 工具错误与 broker 设计 | 修改工具错误契约时参考 |
| `TOOL_ERROR_REVIEW_v2.md` | 工具错误方案的一次审查快照 | 用于历史核对，不代表所有问题仍存在 |
| `OPTIMIZATION_PLAN.md` | 代码审查后形成的待办（含结构重构遗留项） | 逐项重新验证后再实施，不直接视为现存缺陷；完成一项就更新状态表 |

## 辅助与历史文档

| 文档 | 状态 |
|------|------|
| `docs/README.md` | GitHub 浏览 `docs/` 目录时使用的一行入口指针；不维护独立文档清单或事实 |
| `SYSTEM_INVENTORY.md` | 旧 Windows 工作区清单，已被 README 的 Maintenance Map 和本文件取代；保留作历史参考，不作为当前入口 |
| `docs/history/REFACTOR_PLAN_2026-07.md` | 2026-07 完成的结构重构计划（gateway.py、mem_notes、tool_schemas、gateway_tools、recall 拆分）；遗留 Phase 4/5 由 `OPTIMIZATION_PLAN.md` 状态表跟踪 |
| `docs/history/CLAUDE_REVIEW_FOLLOW_UP.md` | 历史 code-review 执行清单；当前状态以 `docs/architecture/AUDIT_MATRIX.md` 为准 |
| `docs/history/PROJECT_MAP_AUDIT_2026-07-14.md` | 2026-07-14 项目地图审查快照；部分建议已在后续文档维护中采纳或修正，不作为当前事实 |
| `docs/history/MCP_INTEGRATION_2026-08-13.md` | 2026-08-13 完成的 MCP 外部工具接入实施稿（网关作为 MCP client，`mcp_registry` / `mcp_routes` / Admin 卡片）；当前事实以 README Maintenance Map 与代码为准 |
| `docs/history/PLAN_STREAM_RESILIENCE_2026-08.md` | 2026-08 完成的流式韧性交接稿（服务端断连后照常读完上游并落库、15s keepalive、PWA 停滞看门狗与尾部对账）；当前事实以 `REQUEST_CONTEXT.md` 流式章节与代码为准 |
| `docs/history/SUPABASE_EGRESS_RECALL_WORKER_2026-08-15.md` | 2026-08-15 Supabase Egress 调查与 Recall worker 回传优化观察档；上线后的计费/更新时间戳核验按该档继续，不把快照当作永久账单结论 |

## 维护原则

- 功能完成、准备推送前，先问：这次是否改变了用户可见行为、架构事实、配置、排障方法或日志含义？只有答案为“是”时才同步对应文档。
- Agent 的实际导航手感是地图维护的证据信号，不是自动改图指令；只有在入口缺失、责任或跨区边界需要靠推测、或同类绕路反复出现时，才更新唯一负责的现行文档。
- 优先更新已有现行文档。只有新主题无法自然归属、且未来确实需要独立维护时，才新增 Markdown。
- 设计稿应标明阶段或历史属性；审查报告是某个时间点的快照，不自动成为长期事实。
- 文档与代码冲突时先核对实现和测试，再修正文档；不要为了让代码符合过时文档而盲目改动内核。
- 不在仓库文档中保存密钥、真实访问令牌或不必要的私人对话内容。
