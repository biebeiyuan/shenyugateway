# Shenyu Gateway Debugging Guide

This guide is the on-demand handbook for production and request debugging. Start from `START_HERE.md`, then come here when the symptom is an upstream error, a stalled stream, a missing tool execution, or a context/cache question. It is not a mandatory pre-read for ordinary code changes.

Commands below assume the authoritative environment: Ubuntu Bash in `/home/yuan/shenyu-gateway`. The Windows SSH command is kept only as an explicitly labelled emergency fallback when the WSL transport path itself is confirmed to be stuck.

For the admin log page itself—round colors, tabs, memory-island content, raw cache values, and assistant lineage—see `LOGS_GUIDE.md`.

## Symptom Triage

Use the smallest first evidence below, then follow the linked stage and owning document. The full request sequence is in [Chat Request Flow](#chat-request-flow) further down.

| 症状 | 第一证据 | 对应阶段 | 所属区域 | 专题文档 |
|------|----------|----------|----------|----------|
| 上游报错、流没有输出或中途卡住 | `python scripts/vps_gateway_logs.py api --via-ssh --errors --detail` | 上游请求 / 流式响应 | 区域二、三 | `docs/architecture/REQUEST_CONTEXT.md`、`LOGS_GUIDE.md` |
| 有工具被提供，但网关工具一次都没执行 | helper 输出的 `tools_offered` 与 `gateway_tools_executed`；Admin 展开日志卡片的“工具执行”页签，看上半段工具清单和下半段实际调用 | 上游返回 / 工具路由前 | 区域三、四 | `docs/architecture/REQUEST_CONTEXT.md`、`LOGS_GUIDE.md` |
| 历史消失、上下文分叉或冷启动桥接不对 | 请求详情与 `context_window_observer.py` 时间线 | 上下文组装 / 窗口 | 区域五 | `docs/architecture/REQUEST_CONTEXT.md` |
| 缓存比例或断点结构不对 | `internal_tool_rounds[].prompt_cache` | provider 适配 / prompt cache | 区域三 | `docs/architecture/REQUEST_CONTEXT.md`、`LOGS_GUIDE.md` |
| Admin 页面打不开或交互失效 | Playwright smoke 与浏览器运行时/同源资源错误 | 前端路由 / 资源 | 区域八 | `README.md` § Maintenance Map |
| PWA 回答里的 Markdown 未显示成样式、刷新后像旧界面，或无法确定正在验收哪一份聊天端 | 精确原文、`renderMarkdown()` HTML、浏览器计算样式、设置页的当前/线上版本 | 客户端渲染 / PWA shell / 部署 | 区域一、八 | 本节「PWA 渲染与版本核验」、`README.md` § Frontend workflow |

## PWA 渲染与版本核验

PWA 的 Markdown 问题必须从用户看到的完整回复开始，不要把某一段单测、某个本地端口，或某次 Service Worker 更新当作最后结论。按下面的证据链逐项收束；只有第 5 步与真实界面都通过，才可以称为用户侧修复。

三条交付原则：

1. 单测、构建和 HTML 断言只能证明各自的技术层，不能替代实际设备上的可见结果。
2. 只有正式 `/chat/` 和设置页中可辨认的当前/线上版本才是验收对象；未知本地端口只是待查预览。
3. 没有在真实设备上看到原始场景的最终结果，就明确写“未验收”，不能用容器健康、缓存更新或局部测试代填。

1. **原文与传输**：保存用户实际看到的完整回复，检查网关日志或 API 返回仍含同一组 Markdown 定界符；分别用 `stream: true` 与 `stream: false` 走一遍。流式阶段可以显示原文，但 completion 后必须用整条 assistant content 渲染，不能拿被思考/工具过程切开的片段做最终 Markdown。
2. **解析 HTML**：以这段精确原文写入或扩展 `pwa/tests/markdown.spec.ts`，确认 `renderMarkdown()` 生成预期的 `<strong>`、`<em>`、链接、代码等 HTML；同时覆盖中文标点紧邻定界符、嵌套强调和未配对星号。
3. **计算样式**：在实际浏览器检查生成标签的 computed `font-family`、`font-weight`、`font-style`、`font-synthesis` 和可见尺寸。HTML 正确但字体没有对应字形时，问题属于 CSS/字体，不要回头改网关响应。
4. **构建与缓存**：运行 `cd pwa && npm test && npm run build`。构建会硬性验证 `dist/build-info.json` 已生成且版本身份已嵌入执行的 bundle；`/chat/build-info.json` 在 Service Worker 中必须始终走网络，不能从 shell cache 读取或写入。再检查正式响应头：`/chat/sw.js` 与 `/chat/build-info.json` 都应是 browser/CDN `no-store`，否则外层 CDN 仍能把旧部署伪装成当前版本。
5. **线上与真实设备**：Coolify 健康后，在实际使用的手机/浏览器打开正式 `/chat/` 的「聊天设置」，确认「当前运行」与「线上已部署」为同一个完整版本，再重放原始场景确认可见样式。线上版本不可读、两个版本不同，或只在未知本地端口看到页面，都属于未验收。

`5174` 是唯一约定的 PWA Vite 开发入口；`/chat/` 是生产入口。其他本地端口只能作为临时预览，必须先从设置页确认其版本来源，不能代替生产验收。

## Error Log Quickstart

For live triage, start with the helper script before changing code:

```bash
python scripts/vps_gateway_logs.py api --via-ssh --errors --detail
```

On POSIX/WSL, the helper pins SSH's optional multiplexing socket under `/tmp/shenyu-gateway-ssh-<uid>/cm-%C`; it does not need to write `~/.ssh`. If the temporary filesystem is unavailable, use the public API path or fix that environment before interpreting an SSH failure as a gateway failure.

The production edge in front of the public gateway blocks default programmatic User-Agents (for example `Python-urllib/3.x`) with **403** even when the Bearer token is correct; the gateway's own auth failures are **401** (or the HTML login page). On a 403, suspect the edge/WAF and set a non-default `User-Agent` before re-checking the token. The helper's own requests already send `shenyu-gateway-debug/1.0` and are unaffected; this bites hand-written `urllib`/`requests` probes.

For prompt-cache, image, epoch, or memory-island questions, start with the compact timeline report. It defaults to `ssh vps`, does not print message content, and follows a stale Coolify container name to the current deployment:

```bash
python scripts/vps_gateway_logs.py cache
python scripts/vps_gateway_logs.py cache --session 6.20 --limit 12
```

The report flags gaps longer than the declared TTL, long-gap hits that suggest relay-side automatic caching, island rewrites, history-branch resets, attachment/image retention, the active tail user-turn guard, cache misses where the relay omitted cache-creation usage, and adjacent requests whose cache-prefix fingerprints stayed identical despite a reported miss.

Cache-prefix fingerprints are protocol-level diagnostics for both Anthropic and OpenAI-compatible payloads. An identical path and fingerprint proves that the gateway emitted the same cacheable prefix after excluding `cache_control` metadata. It does not reveal which upstream node handled the request and is not, by itself, permission to add relay-specific routing, retries, or cache semantics.

For a multi-round tool request, inspect cache evidence in this order:

1. `internal_tool_rounds[].prompt_cache.cache_control_marker_count` and `breakpoints`: prove how many markers were present in the final outbound payload and where the gateway inserted its breakpoints for that round.
2. `internal_tool_rounds[].prompt_cache.prefix_fingerprints`: compare path/fingerprint pairs across requests or rounds to distinguish a gateway prefix change from an upstream miss.
3. The same round's `cache_usage` or raw `usage`: compare provider-reported read, creation, and total input only after confirming the outbound structure.
4. If these content-free fields still cannot resolve the dispute, temporarily enable full payload retention (Admin config「请求日志 → 保留完整请求内容」, or `GATEWAY_LOG_FULL_PAYLOADS=true`; the Admin toggle applies to new requests without a restart), reproduce one small request, inspect the exact `cache_control` blocks, and disable it again.

The Admin **Raw JSON** tab shows the raw request-log object. Without full-payload retention it contains previews, payload summaries, and the per-round cache evidence above, not the complete JSON body sent upstream.

If a request reports `event=branch`, verify that the first differing raw-window message changed semantically. Image expiry, dynamic Operit bundles, and equivalent string/text-block representations are transient client rewrites and must remain in the current epoch. A true branch changes earlier conversational text or tool structure.

Set these in the shell when checking the deployed gateway:

```bash
export SHENYU_GATEWAY_URL="https://gateway.example.com"
export SHENYU_GATEWAY_TOKEN="gateway-api-token"
```

The helper also auto-loads a local ignored config file at `.shenyu-gateway-debug.local.json`, a home config at `~/.shenyu-gateway-debug.json`, or the path in `SHENYU_GATEWAY_LOG_CONFIG`.

Example local config:

```json
{
  "gateway_url": "https://gateway.example.com",
  "gateway_token": "gateway-api-token",
  "ssh_alias": "vps",
  "vps_host": "example.com",
  "vps_user": "root",
  "vps_port": 22,
  "vps_identity": "/home/yuan/.ssh/vps_ed25519",
  "container_match": "shenyu|gateway"
}
```

这是字段示例，不要照抄密钥路径。WSL 下 `vps_identity` 必须是 Linux 可见路径；若使用 `ssh_alias`，让 `~/.ssh/config` 负责主机、用户和密钥配置。

Useful variants:

```bash
# Watch new gateway request errors
python scripts/vps_gateway_logs.py api --via-ssh --watch --errors --interval 5

# Inspect one request by log id or request id
python scripts/vps_gateway_logs.py api --via-ssh --id 84f8b85a

# Parse a retained local JSON log
python scripts/vps_gateway_logs.py local tmp_gateway_log_84f8b85a.json --detail

# Tail VPS/Coolify/Docker logs when SSH is configured
export SHENYU_VPS_HOST="root@example.com"
python scripts/vps_gateway_logs.py ssh --list-containers
python scripts/vps_gateway_logs.py ssh --match "shenyu|gateway" --tail 300 -f
```

Use `api` without `--via-ssh` only when public gateway API access is not blocked by Cloudflare.

`api` and `cache` read a merged view of the live 30-entry process buffer and the bounded SQLite request-log history. With the SQLite directory on a persistent volume, completed request summaries remain available after a Coolify container replacement; use `--limit 200` when an incident may predate the current process. Full Messages, upstream payloads, responses, images, and raw Thinking/signature data are not stored in this history. By contrast, `ssh` mode still runs `docker logs` against the current container only, so deleted-container stdout/stderr is not recovered by the request-log history.

In the WSL Ubuntu workflow, the helper invokes Linux `ssh`. When `ssh_alias` is configured it uses that alias; otherwise it builds the connection from `vps_host`, `vps_user`, `vps_port`, and `vps_identity`. Container lookup first honors configured name/label/service hints, then tries the stable Coolify application prefix and regex match before the slower environment inspection, so a redeploy does not require copying the new random container name into local config.

The script separates `tools_offered` from `gateway_tools_executed`. If tools were offered but zero gateway tools executed, the model/upstream failed before the gateway got any tool call. In that case, inspect upstream errors, relay retries, streaming behavior, request payload shape, and prompt-cache compatibility before editing `gateway_tools.py`.

Do not put gateway tokens, VPS hosts, SSH keys, or API keys into repo files. Use shell environment variables or ask the user for the missing value.

### VPS deployment layout (Coolify)

- The gateway container's NAME changes on every deployment (`<coolify-app-id>-<deploy-stamp>`); its image tag is the git commit sha. Never hardcode a container name — find the live one with `docker ps --format '{{.Names}} {{.Image}}'` (match the sha or the app-id prefix), or let the helper's `container_match` resolve it.
- The production SQLite lives on the named Docker volume `shenyu-gateway-data`, host path `/var/lib/docker/volumes/shenyu-gateway-data/_data/shenyu_gateway.db` (mounted at `/data` in the container). This file survives deployments and container replacement; host-side `python3` can read it directly for read-only probes.
- `/opt/shenyuwangguan` and `/opt/shenyuwangguan-data` on the VPS are stale leftovers of a pre-Coolify deployment. The `.env` and the SQLite there are NOT what the live container uses (that SQLite stopped updating in May 2026) — do not read or edit them when debugging the live gateway. The Supabase credentials in that `.env` do still match production.
- Effective runtime config = container env vars overlaid by SQLite `config_overrides` at startup (overrides win — see the GATEWAY_API_KEY autopsy row). When Coolify env and Admin config disagree, trust `config_overrides`; and keep the Coolify env aligned so a fresh database does not silently flip behavior.

## Context Window Observation

The chunked-window implementation persists content-free observations in SQLite. After the new gateway has handled normal chat, retries, rolls, and tool continuations, summarize the events with:

```bash
python scripts/context_window_observer.py --db data/shenyu_gateway.db
python scripts/context_window_observer.py --db data/shenyu_gateway.db --session-tag 6.20 --json
```

The report includes event classification, epoch reset reasons, retained-message percentiles, raw protected human turns, and memory-island retain/rewrite counts. It does not read or print chat message content. Use this report before tuning the 32-message overflow block or implementing tool-result compression.

## VPS, SSH, and Coolify Operations

Use the configured `vps` SSH alias when present; otherwise use the WSL connection fields from the local debug config. Start with a cheap command and a bounded connection timeout before running Docker or database operations:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 vps date
```

### When WSL SSH stalls

WSL SSH can occasionally connect but stall during key exchange, commonly after printing `expecting SSH2_MSG_KEX_ECDH_REPLY` under `ssh -vv`. This is a transport-path problem, not evidence that Docker, Coolify, or the target command is broken. First inspect and stop only the stuck WSL processes from the current attempt. Only when that transport issue is confirmed should you use the Windows fallback below:

```bash
ps -eo pid,ppid,etime,args | grep '[s]sh .*vps'
kill 12345  # replace with a stuck PID from this debugging attempt
```

**Windows emergency fallback only:** retry the cheap probe with the host's `ssh.exe` from PowerShell. This is not the normal project shell.

```powershell
Get-Command ssh
ssh -o BatchMode=yes -o ConnectTimeout=10 vps date
```

Do not diagnose the Docker daemon from a hanging `docker ps` until a plain `ssh vps date` succeeds reliably. This separates SSH transport trouble from a real remote Docker problem.

### Avoid nested shell quoting

The local Bash shell, remote shell, `docker exec`, SQL, Python, and PHP each have different quoting rules. Pipes, `$()`, variables, regex `|`, and nested quotes can be consumed by the wrong shell. For a multiline read-only script or SQL statement, encode the payload locally, decode it on the VPS, and pass it through stdin:

```bash
payload=$(cat <<'SQL'
select status from application_deployment_queues where deployment_uuid = 'example';
SQL
)
encoded=$(printf '%s' "$payload" | base64 -w0)
printf '%s' "$encoded" | ssh vps "base64 -d | docker exec -i coolify-db psql -U coolify -d coolify -At"
```

Base64 here is only a quoting transport, not secret protection. Never print or commit an encoded API key, and keep secret-bearing payloads out of retained shell history and logs.

### Persist Coolify environment changes correctly

Coolify stores `environment_variables.value` using Laravel encryption. A plaintext `INSERT` or `UPDATE` against `coolify-db` creates an unreadable configuration even if the row looks valid. Use the Coolify UI/API or boot Coolify's Laravel application and write through `App\Models\EnvironmentVariable`, which applies the encrypted cast and creates the expected preview row.

After changing environment variables, `docker restart` is insufficient because it reuses the existing container environment. Queue a Coolify deployment with `restart_only: true`, or use the equivalent Coolify UI/API action, so Compose recreates the application container without unnecessarily rebuilding the image.

Verify in this order:

1. Coolify deployment queue reaches `finished` rather than merely `queued`.
2. The new container is `healthy` and still uses the intended image/commit.
3. Runtime config reports only safe facts such as `key_configured=true`, model, dimensions, worker flags, interval, and batch size. Never print the key.
4. Worker logs show startup and successful source/index requests.
5. Database status counts move from `pending` or `failed` to `ready`.
6. Run one end-to-end application query and print only bounded identifiers, source types, and titles.

### Validate external API keys from the production path

A local WSL proxy or TLS path can return a misleading authentication error even when the key works from the VPS. Validate an embedding or upstream key from the production container/network path with the same base URL, model, and proxy policy used by the gateway. Treat local and VPS disagreement as a network-path signal; do not persist a key until the VPS request succeeds, and do not reject a key solely because the local proxy path failed.

## First Rule

Preserve behavior before cleanup. This gateway has browser-facing contracts outside this repo, and code can look unused from the admin UI while still being used by `home-frontend`.

Do not commit one-off test files. Prefer `python -c`, temp directories, or existing `test_*.py` files. If a temporary test script is created in the repo, delete it before committing unless it is intentionally promoted into a permanent regression test and documented.

## Symptom Autopsy Index

这里只在根因已经由日志、代码或测试确认，并且修复完成后新增一行。这是给下一位排障者搜索的已确认故障索引，不是完整复盘记录。

1. **症状**：只写用户、调用方或管理员实际看到的现象，不提前写只有定位后才知道的内部术语。
2. **根因文件与错误**：列出定位根因所需的最小文件路径，并用一句短语说明哪里判断、状态或协议处理错了；修复过程留在 Git 历史中。
3. **一句话教训**：写给下一个遇到相似现象的人，优先使用“先查 X，再查 Y”这类可以直接执行的排查顺序或判定规则，不写空泛总结。

已经确认的排查顺序属于“一句话教训”；未经验证的猜测、一次性排查流水账和聊天复述不进入这里。

| 症状 | 根因文件与错误 | 一句话教训 |
|------|----------------|------------|
| PWA 回答里的 `**重点**` 已被解析却看不出加粗或斜体，聊天框在输入和换行时又会改变外观或高度 | `pwa/src/styles.css`、`pwa/src/App.vue`、`pwa/index.html`：Anthropic 字体只声明了 normal 字形，而全局 `font-synthesis: none` 让 `<em>` 无法合成斜体；输入框结构、自动高度上限和移动键盘视口处理也曾与参考实现分叉 | 先检查 Markdown 是否已生成 `<strong>/<em>`，再看计算后的字体、字重和 `font-synthesis`；输入框跳动则逐项对照 DOM 层级、统一高度上限与 `visualViewport` 处理，不要先改消息协议 |
| PWA 助手回答前半段正常、后半段仍显示 `**` 等 Markdown 符号，刷新后还像是旧界面 | `pwa/src/stream/timeline.ts`、`pwa/src/markdown.ts`、`pwa/src/main.ts`、`pwa/public/sw.js`：过程条/思考片段把 Markdown 定界符拆到不同内容片段，`marked` 对中文标点紧邻强调闭合符以及混合/未配对星号的边界也不会按直觉闭合，Service Worker 又长期复用同一 `v2` shell 缓存，旧 worker 接管新 shell 后页面仍不重载 | 先确认流式阶段只展示原文、完成后才对整条正文解析，再验证中文强调边界、嵌套/未配对分隔符和完整回复；最后查 Service Worker 缓存版本、导航是否强制取最新 `index.html`，以及新 worker 接管时页面是否重载 |
| PWA 接入已有线程后上下文重复、前缀从零开始或被误判为分支 | `pwa/src/App.vue`、`shenyu_gateway/gateway_admin_routes.py`、`shenyu_gateway/sessions.py`：接入动作把仅供检查的 `gateway_messages`/`recent_messages` 当成客户端历史，丢失了 `request_context_snapshots` 保存的裁剪窗口 | 线程交接先读最新 `context_snapshots[0].messages`；`recent_messages` 只能作为旧数据回退，不能重建请求历史 |
| PWA 修复后刷新仍把同一轮重复历史发回网关，且 roll 会吞掉旧回答 | `pwa/src/App.vue`：旧接入流污染了 `localStorage`，启动只恢复本地数组；roll 直接截断 assistant 消息而没有候选版本 | 先清理本地完全重复行并用干净 cold-start source 重绑线程，同时保留之后的新消息；roll 应保留同一 assistant turn 的候选并只发送当前选中版本 |
| PWA 已点击清理仍看到旧回答重影，且重复集中在历史上半窗 | `pwa/src/App.vue`、`shenyu_gateway/prepare_messages.py`、`shenyu_gateway/context_window.py`：本地清理没有结束 active cold-start；桥接只做首尾连续去重，无法发现桥接与完整 PWA 历史之间的跨层重叠 | 先看 `cold_start_bridge_overlap_messages` 和 active snapshot；PWA 达到完整客户端窗口后应直接停用临时桥接，不再依赖全局重复清理 |
| 无痕窗口不登录也能打开聊天并正常发消息，管理配置和模型列表也直接返回成功 | `gateway.py`、`shenyu_gateway/store/_admin.py`：SQLite `config_overrides` 中持久化的空 `GATEWAY_API_KEY` 在启动时覆盖了容器里已配置的非空密钥 | 遇到“部署环境明明有 key 但公网仍免登录”，先用无 token 请求验真实状态，再查 SQLite 配置覆盖，不能只看容器环境变量 |
| 连续多轮聊到新的 Stars 内容，记忆岛仍停在旧内容；直接点名某颗星也不切换 | `shenyu_gateway/stars/_recall.py`、`shenyu_gateway/context_builder.py`、`shenyu_gateway/memory_island.py`：直接点名、旧星失效和窗口重置等强制改写原因没有完整传到小岛决策，`2/3` 重叠粘性仍保留旧内容 | 遇到“候选已变但岛不换”，先查强制改写原因是否生成并贯通，再查重叠粘性是否仍把新提案拦回去 |
| 冷启动首轮能看到源线程，下一轮只剩客户端尾部消息，桥接没有继续增长到高水位再剪裁 | `shenyu_gateway/store/_cold_start.py`、`shenyu_gateway/prepare_messages.py`：注入计数达到 `max_injections=1` 就停用快照，且完全重叠被误判为桥接已剪掉 | 先查快照是否仍 active，再查 `cold_start_bridge_messages` 是否因滑动窗口真正归零；客户端重复带回历史不等于桥接已经可以销毁 |
| 沈予在书架看得到矛盾书名，却连续换参数仍打不开或无法批注 | `shenyu_gateway/tool_registry.py`、`shenyu_gateway/tool_schemas.py`、`shenyu_gateway/conflict_books.py`：daily 只暴露读取且读取只收 UUID，书架提供的精确标题没有可用读取路径 | 先对照生产工具 enum、broker 描述和书架实际给出的定位字段；模型看得到的书名必须能被读写工具直接接受 |
| 沈予能按精确书名读来历书，但忘记书名时 `shenyu_books` 没有办法浏览目录，`read origin` 只提示要 `book_id` 或 `title` | `shenyu_gateway/tool_schemas.py`、`shenyu_gateway/gateway_tools/_books.py`、`shenyu_gateway/resident_books.py`、`shenyu_gateway/conflict_books.py`：共享书架已有内部 overview/list，却漏了公开 `action=list` 和可继续读取的 `book_id` | 多本对象的 read 需要定位字段时，先确认同一公开工具是否提供不含正文的 list，并让 schema、broker 提示、错误引导和 list 返回字段形成完整的“浏览→定位→读取”链 |
| `shenyu_add_calendar` 按说明传 `period_type=week` 和 `date=YYYY-MM-DD`，工具页出现 `not enough values to unpack` 真异常 | `shenyu_gateway/tool_registry.py`、`shenyu_gateway/calendar.py`：自然日期别名未经转换就送进只接受 `YYYY-Www` 的周键解析器 | 先查 schema 承诺的自然输入是否在 handler 边界归一化，再查周期解析器；不要让调用方替内部键格式兜底 |
| 前端翻开“家现在”时，同时出现自动家况和一份空白可写正文，看起来像两本重叠的书 | `shenyu_gateway/resident_books.py`、`supabase/migrations/20260719_shenyu_books.sql`、`admin/src/views/ConflictView.vue`：`home` 被误建成可写 living book，自动快照只作为附加字段挂在空正文旁边 | 遇到“自动视图旁又多一份可编辑正文”，先确认对象的唯一事实来源，再查数据库类型、工具 write 权限和前端编辑控件是否都服从同一边界 |
| PWA 流式回答在完成前不逐字出现，像最后一次性弹出；工具进度也只在结束时出现 | `pwa/src/App.vue`：assistant 入数组后继续修改脱离 Vue 代理的草稿对象，SSE 增量和 `shenyu_tool` 事件没有触发渲染 | 先确认每个 SSE 增量是否写回响应式消息状态，再查上游或代理是否真的分块发送 |
| PWA 发送图片时网关返回 HTTP 400，提示 `image_url` 不是上游允许的内容类型 | `shenyu_gateway/upstream_adapter.py`：OpenAI-compatible 图片块进入 Anthropic 出口时被原样透传，没有转换为 Anthropic `image`/`source` 块 | 先确认网关公共入口仍是 OpenAI-compatible，再检查 Anthropic 出口是否把 `image_url` 转成 `image`；不要让客户端跟着上游切私有格式 |
| 档案页日历大段日期无痕迹，整天聊天挤在同一时间戳上，气泡顺序颠倒；换会话后旧消息重复出现两份 | `shenyu_gateway/chat_archive.py`、`shenyu_gateway/store/_admin.py`：`event_at` 只认 Operit 时间标记不认 PWA 状态后缀，窗口深处一枚旧标记把后续所有消息拖到同一时刻；seen-hash 按 session_tag 隔离，历史交接进新 session 被整窗重归档 | 档案时间错乱先抽查 Supabase 里 `event_at` 是否大量相同、再对比 `archived_at` 跨度；跨会话重复先查 `chat_archive_seen` 的去重作用域是不是 per-session |
| 拉日志感觉最近的 PWA 聊天没拼进请求，Messages 列表比实际发送条数短且每条被截短 | `shenyu_gateway/request_logs.py`、`admin/src/views/LogsView.vue`：持久化快照对消息预览做头部切片只留最早 100 条，默认又不保留完整 payload，Messages 页对列表截断没有任何提示 | 先对比 `prepared_messages_count` 与预览条数，再看 `persisted`/`persistence_truncated`，别把持久化预览当完整请求；要全文就开「保留完整请求内容」再看之后的新请求 |
| 沈予 review 星星时返回 `count=0`、`items=[]`，却同时显示还有多颗 `remaining_unreviewed` | `shenyu_gateway/stars/_review.py`：取本批星星时误用当前聊天 `session_tag` 限定来源，但剩余数统计的是全库，导致两者范围不一致 | review 数量互相矛盾时先逐项比较种子查询和剩余计数的过滤条件；当前聊天标签只能记录 review 来路，不能切割住户级星星队列 |
| 后台家里地图永远显示 room/home 两处待复核，本地 `resident_home.py check` 全绿，review 与住户签字都无法清除 | `Dockerfile`、`resident_home_manifest.json`：room 是 manifest 源文件 `pwa/src/meta/roomEntry.ts` 未 COPY 进生产镜像；home 是 `Dockerfile` 本身在 manifest 指纹范围内，而 Coolify 构建时会把全部配置环境变量（含密钥）注入成 ARG 行改写它，容器内永远没有与仓库一致的版本可校验 | 线上待复核但本地全绿时，先比对 `/api/project-map` 组件返回的 files 列表与本地 manifest globs 命中集；构建平台会改写的文件（如 Coolify 注入 ARG 的 Dockerfile）不能进指纹范围，也不要把它 COPY 进镜像留下密钥落点 |

## Module Map

The canonical file inventory is `README.md` § Maintenance Map — it is guarded by `tests/test_project_map.py` (full coverage of top-level modules, packages, and frontend files; stale paths fail CI), so this guide does not keep its own copy. When you need "which file does X", read the map there. Debugging-specific ownership rules live in this file's Refactor Boundaries section; the tool dispatch order (registry first, then implementation) is described under Chat Request Flow.

## Chat Request Flow

The chat route is wired in `gateway.py`; `ChatPipeline` owns the request orchestration:

1. Auth middleware allows `OPTIONS` and accepts both `Authorization` and `?token=...`.
2. The chat route calls `_chat_pipeline(store).run()`; `gateway.py` supplies the pipeline's runtime dependencies.
3. `ChatPipeline` calls `shenyu_gateway.prepare_messages.prepare_messages()` through the thin `_prepare_messages()` wiring adapter.
4. `prepare_messages()` opens the gateway session, stores the raw request window, classifies history, restores eligible cold-start and pending-tool context, trims client messages, writes a request context snapshot, and builds the mode-specific context package. `ContextBuilder` supplies Calendar, heartbeat, Memory Island, or Room data as appropriate.
5. `shenyu_gateway.context_layers` renders the package into:
   - `stable`: charter and optional wake welcome message.
   - `slow`: calendar memory and the unified bookshelf overview in normal/Room contexts.
   - `mem`: active mem notes headed by `## 我之前写下的便签，可能用的到。`, after `slow` and before heartbeat.
   - `heartbeat`: independent `## 我之前的心跳` block after `mem`.
   - `tool_policy`: compact `## 工具怎么用` reminder after heartbeat.
   - `format`: private heartbeat format reminder after tool policy.
6. `_build_upstream_request()` prepares the upstream payload.
7. `shenyu_gateway.upstream_adapter` converts OpenAI-compatible messages/tools to Anthropic when needed, adds cache markers, and converts responses/chunks back.
8. The tool path may call gateway tools. Response capture strips private `<heartbeat>` blocks before visible output is logged or sent; `[mem]...[/mem]` and `[star]...[/star]` remain visible text, and durable Mem/Star writes happen only through their tools.

For native Anthropic tool turns, the gateway temporarily preserves the upstream Thinking/redacted blocks and their opaque signatures so the next tool-result request can continue the same provider transcript. The first request's Thinking configuration and effort are pinned only for that unfinished tool turn; changing the admin effort setting affects the next new turn, not a tool turn already in progress.

Pending tool context is restored only when the returned history still matches the original session, tool-call ids, visible assistant text, tool names, and arguments. If the user rolls a reply, edits the assistant text, changes tool arguments, or continues from another branch, the gateway leaves the client history unchanged and does not reattach the original hidden blocks.

When Anthropic Thinking or tool continuation looks wrong, inspect one request in this order:

1. `upstream_payload_summary.thinking`: proves what Thinking mode the gateway requested, not what the model returned. To confirm the exact `output_config.effort` sent for that round, temporarily enable full payload retention (Admin toggle or `GATEWAY_LOG_FULL_PAYLOADS=true`) and inspect `upstream_payload.output_config.effort`.
2. `upstream_response_evidence`: compare `upstream.thinking_content_seen` with `normalized.thinking_content_seen`. Raw false means no standard visible Thinking reached the gateway; raw true and normalized false identifies the adapter boundary; both true moves the investigation to the client parser/display. The same content-free counters exist for streaming, non-streaming, and each `internal_tool_rounds[]` entry.
3. `internal_tool_rounds[].anthropic_thinking`: `preserved=true` proves native Thinking/redacted blocks were captured for an unfinished tool continuation; `signature_present` and `redacted_present` are safe boolean evidence only.
4. `pending_gateway_tool_turns_injected`: confirms whether a matching pending transcript was restored into the continuation.
5. `pending_gateway_tool_lineage_mismatches`: a non-zero value means the saved transcript was deliberately rejected because the returned client history no longer matched.

Never treat opaque signature or redacted Thinking data as readable chain-of-thought, and never add it to request logs. `upstream_response_evidence` stores fixed counters and booleans only; it is not a raw-response capture and intentionally cannot name or expose a relay's unknown private fields. A sent `thinking` parameter without `anthropic_thinking.preserved=true` says nothing conclusive about a final visible reply; use the raw-versus-normalized response evidence instead.

Native Claude Code and Shenyu's OpenAI-compatible surface can use different Thinking request shapes. A Claude Code request may use `thinking.type=enabled` with a token budget, while the gateway may normalize an OpenAI request to `thinking.type=adaptive` and an `output_config.effort`; compare the actual upstream payload and event counters before attributing a difference to client rendering. Claude Code receives native `thinking_delta` events, whereas a gateway client receives non-empty Thinking as `choices[].delta.reasoning_content` (or `message.reasoning_content`).

Tool schemas and name dispatch live in `shenyu_gateway/tool_registry.py`; implementation methods live in the `shenyu_gateway/gateway_tools/` mixin package. If a tool is visible but behaves wrong, check `tool_registry.py` dispatch first, then the matching mixin method in `gateway_tools/`.

### Gateway tool error log chain

The Admin “工具报错” page does not read the ordinary request-log error list. Gateway-tool results with `ok: false` are recorded by `shenyu_gateway/tool_loop.py::_record_tool_error()` into the dedicated SQLite `tool_error_log` table through `shenyu_gateway/store/_admin.py`. `shenyu_gateway/gateway_admin_routes.py` exposes them at `GET /api/gateway/tool-errors`, while `admin/src/api/toolErrors.ts` feeds `admin/src/views/ToolErrorsView.vue`.

When the page shows a tool failure, inspect this dedicated chain first; `python scripts/vps_gateway_logs.py api --errors ...` only filters request-level logs and can legitimately return no matches. Read these fields together:

- `tool_name` and `target_tool`: distinguish the broker (`shenyu_gateway_tool`) from the actual target tool.
- `args_json`: verify the broker envelope and target arguments without assuming the model used the visible schema correctly.
- `error_kind=validation`: the call was rejected by its contract or returned a validation-style failure.
- `error_kind=config`: required runtime configuration was unavailable.
- `error_kind=exception`: the tool entered execution and raised a real code or dependency exception.
- `error_source=result|execute`: distinguish a structured `ok: false` result from an execution exception.

For a direct read, use `GET /api/gateway/tool-errors?limit=50`; add `&kind=validation`, `config`, or `exception` when narrowing the list. Do not confuse this durable SQLite table with the live request deque or bounded request-log history.

For quick live triage, call `GET /api/gateway/debug` from the admin session. It returns masked config, upstream routing, tool mode, store overview, and latest request/error IDs without dumping the full prompt payload.

Gateway tool descriptions are intentionally short because they enter the model tool context. Keep them to one-line purpose plus backing pool/table. Put detailed usage notes in `shenyu_supabase_guide` or docs, not in every parameter description.

Useful boundary map:

- Broker mode exposes only `shenyu_gateway_tool`; call it with `tool` set to the full gateway tool name, including the `shenyu_` or `supabase_` prefix, and put the selected tool's arguments in the `params` object, not a JSON-encoded string. The old `arguments` field is still accepted for compatibility.
- `shenyu_recall`: visible unified recall tool; returns a bounded excerpt and source id. Indexed document sources cover `memory`, `journal`, `windowsill`, settled normal `heartbeat`, `room`, `board`, `calendar`, and `notebook`; stars, active mem notes, and recent live heartbeats are federated through their specialized paths. Full recall traces stay in gateway logs.
- `shenyu_recall_read`: reads the full original selected by `source_type + source_id`.
- `shenyu_list_mem_notes`: visible mem-note browse/review tool; reads Supabase `shenyu_mem_notes`.
- `shenyu_ask_memory`: deprecated compatibility name; direct or broker calls are rejected with `error_kind=validation`. Use `shenyu_recall` with `source_types=["memory"]`.
- `shenyu_search_primary_texts`: deprecated compatibility name; direct or broker calls are rejected with `error_kind=validation`. Use `shenyu_recall` with the matching source types.
- `shenyu_surface_passages`: removed 2026-07-26 (it was never in the visible tool schema and lost its last consumer with the calendar-generation removal); calling it now returns the deprecation message pointing to `shenyu_recall`.
- `shenyu_search_mem_notes`: visible mem-note search tool; reads Supabase `shenyu_mem_notes`.
- `shenyu_read_heartbeat`: gateway tool; reads SQLite `heartbeat_entries`.
- `supabase_*`: gateway fallback tools for direct Supabase table operations.
- `GATEWAY_TOOL_MODE=broker`: exposes one compact `shenyu_gateway_tool` that dispatches to the same gateway-native tools. Use `full` when the model needs stricter per-tool parameter schemas.
- `query_memory` and `get_memory_by_title`, when visible, are client-provided tools from outside the gateway; inspect the client/Operit tool definitions for their backing pool.

## Context Layer Debugging

When context looks wrong, inspect in this order:

1. `cfg` flags: `MAX_CLIENT_MESSAGES`, `ENABLE_COLD_START`, `CALENDAR_INJECT_*`, `INJECT_MEM_NOTES`, `ENABLE_GATEWAY_TOOLS`, `GATEWAY_TOOL_MODE`.
2. `_prepare_messages()` metadata: `client_message_window`, `cache_layers`, `cold_start_snapshot`, `upstream`.
3. SQLite tables:
   - `raw_request_windows`: original client payload before trimming.
   - `request_context_snapshots`: trimmed client window before gateway layers; used by cold start.
   - `cold_start_snapshots`: bounded bridge packages.
   - `heartbeat_entries`: global heartbeat pool.
4. `ContextBuilder.build_context_package()` to confirm which sources were fetched.
5. `context_layers.render_layered_additions()` and `context_layers.assemble_layered_messages()` to confirm layer placement.

Layer order in the final request:

```text
tools
stable system
slow system
mem system
heartbeat system
tool_policy system
format system
cold-start bridge messages, when active
trimmed client history
latest user
```

Prompt-cache markers target request tools, `stable`, `slow`, and `format` when those layers exist. The `format` marker follows the reading order and therefore includes any preceding mem/heartbeat/tool-policy blocks; a changing mem note can invalidate that marker without affecting the earlier stable/calendar markers.

## Calendar Debugging

Calendar diary pages are handwritten by 沈予 through the `shenyu_add_calendar` gateway tool (`gateway_tools/_calendar.py`, versioned append/replace into Supabase `calendar_pages`); there is no gateway-side generation pipeline. `CalendarService` is a slim read-only service (month_status + page_detail) backing the `GET /api/calendar/month` and `GET /api/calendar/page/{page_id}` read endpoints.

If a page looks wrong, check the tool-error chain for `shenyu_add_calendar` first, then Supabase `calendar_pages` directly. For context injection of calendar memory, check the `calendar_inject_day/week/month`, `calendar_context_*_limit`, and day-only `calendar_context_day_offset` config keys plus the `## Calendar Memory` slow layer. Day pages are ordered by `period_start`; the offset skips written pages, not elapsed calendar days.

## Response Capture Debugging

Private assistant tags are parsed in `response_capture.py`:

- `AssistantTagFilter` supports chunked streaming input. It withholds partial `<heartbeat>` tags until they close or are flushed. Inline `[mem]` and `[star]` tags are left visible in assistant output (capture is now via tool calls only).
- `split_private_assistant_tags()` is the non-streaming helper.
- `store_heartbeat()` writes heartbeat rows through `GatewayStore`.

Visible output should never include closed private blocks:

- `<heartbeat>...</heartbeat>` is removed and written to `heartbeat_entries`.
- `[mem]` and `[star]` tags are left visible in assistant output; mem notes and stars are created exclusively via tool calls (`shenyu_write_mem_note`, `shenyu_create_star`).
- Incomplete heartbeat is captured and hidden on flush.

When this area breaks, check `test_gateway_tags.py` and `test_response_capture.py` first.

## External Frontend Contracts

These are hard contracts with `home-frontend`; do not remove or reshape them during cleanup:

- `GET /api/gateway/heartbeats?token=...&limit=2000&order=asc&scope=normal`
  - Query token auth must work.
  - Keep `limit`, `order`, and `scope`.
  - Return JSON with `heartbeats`.
  - Each heartbeat must include at least `content` and `created_at`.
  - `scope=normal` reads `heartbeat_entries`; unknown scopes (including the retired `hisense`) return 200 with an empty list.
- `GET /api/calendar/month?token=...&month=YYYY-MM`
  - Return `grid`.
  - Each day item must keep `date`, `day`, `in_month`, `has_day`, `has_week`, and `day_page.id/title/summary/status` when present.
- `GET /api/calendar/page/{page_id}?token=...`
  - Return at least `id`, `title`, `summary`, and `content`.

Browser behavior to preserve:

- `/api/*` accepts `?token=...` because the external frontend intentionally avoids `Authorization` headers to reduce CORS preflight.
- `OPTIONS` must not be blocked by auth middleware.
- Keep CORS origins listed in `README.md`, including `null`.

Permanent test coverage for these contracts is in `tests/test_external_contracts.py`.

## Verification Checklist

After Python changes:

```bash
python -m py_compile gateway.py shenyu_gateway/store/__init__.py shenyu_gateway/stars/__init__.py shenyu_gateway/context_layers.py shenyu_gateway/response_capture.py shenyu_gateway/upstream_adapter.py tests/test_external_contracts.py tests/test_gateway_context.py tests/test_gateway_tags.py tests/test_gateway_trim.py
git diff --check
rg -n '淇|閺|鈹|銆|锛|紝|娌堜簣' README.md DEBUGGING_GUIDE.md gateway.py shenyu_gateway tests
```

If the local environment has `pytest` available:

```bash
python -m pytest tests/test_gateway_trim.py tests/test_gateway_tags.py tests/test_gateway_context.py tests/test_external_contracts.py
```

If `pytest` is unavailable, install/use the WSL Python environment or run a no-file `TestClient` smoke test with a temporary SQLite database. Do not route ordinary work through WindowsApps Python and do not leave one-off smoke scripts in the repo.

## Refactor Boundaries

- Keep routes thin; push logic into services or helper modules.
- Keep query-token auth and CORS behavior in `gateway.py`, near the middleware and routes.
- Keep SQLite behavior in `GatewayStore`.
- Keep Supabase HTTP mechanics in `SupabaseClient`.
- Keep context rendering and message-window surgery in `context_layers.py`.
- Keep private response tag filtering and heartbeat capture helpers in `response_capture.py`.
- Keep upstream protocol conversion in `upstream_adapter.py`.
- Add comments only where they protect external contracts or explain non-obvious behavior.
