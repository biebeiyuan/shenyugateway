# Shenyu Gateway 文档地图

这份文件回答两个问题：新线程应该先读什么，以及根目录里的 Markdown 分别是不是当前事实。项目规则尽量留在仓库中，避免只存在于某个模型的全局记忆里。

## 新线程入口

权威的最短顺序只有三步：

1. Coding agent 先遵守 `AGENTS.md`；这通常由工具自动加载，不要求人额外阅读。
2. 人和 agent 都从 `START_HERE.md` 选择当前任务入口。
3. 只读该任务指向的现行专题文档和代码；不默认预读其他设计稿或 Debug 文档。

需要快速认识文件时，读 `README.md` § Maintenance Map 和 `docs/architecture/SYSTEM_ZONES.md`。需要判断一份 Markdown 是否仍是当前事实时，查本文件后续状态表。`DESIGN.md` 只在准备修改记忆或上下文内核时阅读相关章节；`DEBUGGING_GUIDE.md` 和 `LOGS_GUIDE.md` 都是按需参考。

## 内容归属

| 内容 | 主要文档 | 不应重复放置 |
|------|----------|--------------|
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
| `README.md` | 当前项目入口、架构和维护地图 | 模块、配置、API、部署或主要行为改变时 |
| `docs/architecture/SYSTEM_ZONES.md` | 现行代码分区、跨区桥梁和审计入口 | 模块责任、主要调用链或边界改变时 |
| `docs/architecture/AUDIT_MATRIX.md` | 分区风险、证据、测试缺口和审计顺序 | 风险被证实、排除、修复或测试覆盖改变时 |
| `docs/architecture/REQUEST_CONTEXT.md` | 请求、上下文、缓存、存储、归档和外部契约参考 | 这些子系统的现行行为改变时 |
| `docs/architecture/MEMORY_ROOM.md` | Mem、Stars、Room 和 private capture 参考 | 这些子系统的现行行为改变时 |
| `DESIGN.md` | 记忆、召回、上下文编排的长期原则和改动边界 | 核心语义或系统不变量改变时 |
| `DEBUGGING_GUIDE.md` | 当前请求链路、诊断方法和验证清单 | 日志字段、运维方式或排障路径改变时 |
| `LOGS_GUIDE.md` | 面向日常使用的日志页速查 | 日志页的含义、标签或展示方式改变时 |
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

机械护栏与语义提醒分开处理：`tests/test_project_map.py` 对 README 运行文件覆盖、DOCS_MAP 现行文档路径和 SYSTEM_ZONES 核心路径做红灯检查；`scripts/check_audit_freshness.py` 只根据 AUDIT_MATRIX 的最近复核日期、关联路径、Git 最近修改和当前工作树给黄灯提醒，始终不把“文件后来改过”判定成事实已经过期。

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
| `REFACTOR_PLAN.md` | 文件拆分重构计划 | 做结构重构时核对，完成状态以当前代码为准 |
| `OPTIMIZATION_PLAN.md` | 代码审查后形成的待办 | 逐项重新验证后再实施，不直接视为现存缺陷 |

## 辅助与历史文档

| 文档 | 状态 |
|------|------|
| `docs/README.md` | GitHub 浏览 `docs/` 目录时使用的一行入口指针；不维护独立文档清单或事实 |
| `SYSTEM_INVENTORY.md` | 旧 Windows 工作区清单，已被 README 的 Maintenance Map 和本文件取代；保留作历史参考，不作为当前入口 |
| `docs/history/CLAUDE_REVIEW_FOLLOW_UP.md` | 历史 code-review 执行清单；当前状态以 `docs/architecture/AUDIT_MATRIX.md` 为准 |
| `docs/history/PROJECT_MAP_AUDIT_2026-07-14.md` | 2026-07-14 项目地图审查快照；部分建议已在后续文档维护中采纳或修正，不作为当前事实 |

## 维护原则

- 功能完成、准备推送前，先问：这次是否改变了用户可见行为、架构事实、配置、排障方法或日志含义？只有答案为“是”时才同步对应文档。
- 优先更新已有现行文档。只有新主题无法自然归属、且未来确实需要独立维护时，才新增 Markdown。
- 设计稿应标明阶段或历史属性；审查报告是某个时间点的快照，不自动成为长期事实。
- 文档与代码冲突时先核对实现和测试，再修正文档；不要为了让代码符合过时文档而盲目改动内核。
- 不在仓库文档中保存密钥、真实访问令牌或不必要的私人对话内容。
