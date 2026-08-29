# 交付验收正本

这篇是整个仓库（不限前端）交付验收的唯一正本：状态怎么填、什么时候探生产、
施工簿的 verification 该记什么。`AGENTS.md` 的交付日志段、PWA 铁律段和
`docs/frontend/STYLE_AND_CRAFT.md` 的验收小节都链接到这里，不再各自复述。

## 交付状态梯

交付状态只有四档，如实填报，不越档汇报：

| 档 | 含义 | 充分证据 |
|---|---|---|
| `verified_local` | 本地测试/构建通过，未推送 | 测试与构建输出 |
| `pushed` | 已推送目标分支 | `git push` 回执的 `旧hash..新hash` 区间即充分证据，无需 `ls-remote`/fetch 复核；汇报附 commit hash |
| `deployed` | 生产已部署该改动 | 版本接口、生产日志或可识别的构建哈希 |
| `device_verified` | 已在真实设备复现原场景并确认修复 | 手机实机在生产 `/chat/` 页的观察 |

## 探针边界

版本接口、生产日志、生产 `/chat/` 页这类探针只属于 `deployed` / `device_verified`
两档——它们探的是运行中的服务本身，不是 git。改动只到 `pushed` 档（例如纯后端 commit）时，
push 回执就是终点证据，不要再去探生产。

前端专属的验收规则（PWA 三铁律、手机视口第一现场、缓存归因纪律）在
`docs/frontend/STYLE_AND_CRAFT.md` § 前端验收铁律，只适用于「PWA 用户可见修复
交付生产」这一类交付，不套用到纯后端或未到 `deployed` 档的改动。

## 验证基线与施工簿记法

以下基线适用于每一次有意义的交付，在这里定义一次，不在施工簿逐条复述：

- 受影响的 Python / 前端定向测试通过；跨模块改动跑全量。
- 地图覆盖路径变化时 `python -m pytest -q tests/test_project_map.py` 通过。
- `python scripts/resident_home.py check` 八组件 ok（触发 review 时按 `AGENTS.md` 流程确认）。同一条命令会报出本次改动碰过、行尾却不是纯 LF 的文件并判红，先规范行尾再复核；没碰过的旧文件只列出来提示，不算不通过。
- `git diff --check` 通过。
- 中文文本变化时按 `AGENTS.md` § Encoding Rules 扫乱码。

`project_delivery_log.jsonl` 的 `verification` 只记两类内容：一句「验证基线通过」
（或指出哪一项例外及原因），加上本条交付特有的证据——例如实机观察、push 回执区间、
新增测试覆盖了什么。不要把上面的基线清单逐项抄进每条记录。
