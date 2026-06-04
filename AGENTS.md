# Shenyu Gateway Agent Notes

## Encoding Rules

- Treat source, Markdown, and config files as UTF-8.
- When reading files in Windows PowerShell, use `Get-Content -Encoding UTF8`.
- Do not use PowerShell redirection, default `Set-Content`, or default `Out-File` to write files that contain Chinese text.
- Prefer `apply_patch` for edits. Do not shell-concatenate large Chinese text into source files.
- If Python files changed, run `python -m py_compile` before handing off.
- If Chinese text changed, scan for mojibake markers: `淇`, `閺`, `鈹`, `銆`, `锛`, `紝`, `娌堜簣`.
- If garbled text appears, first decide whether it is terminal display trouble or real file damage.

## First Debug Move

When the user reports gateway, Coolify, VPS, upstream, streaming, or tool-call trouble, check logs before guessing.

Use the helper:

```powershell
python scripts\vps_gateway_logs.py api --via-ssh --errors --detail
```

Expected environment variables:

```powershell
$env:SHENYU_GATEWAY_URL="https://gateway.example.com"
$env:SHENYU_GATEWAY_TOKEN="gateway-api-token"
```

The helper also auto-loads a local ignored config file at `.shenyu-gateway-debug.local.json`, or a home config at `~/.shenyu-gateway-debug.json`, or the path in `SHENYU_GATEWAY_LOG_CONFIG`.

Config shape:

```json
{
  "gateway_url": "https://gateway.example.com",
  "gateway_token": "gateway-api-token",
  "vps_host": "example.com",
  "vps_user": "root",
  "vps_port": 22,
  "vps_identity": "C:/Users/曾/.ssh/cyberboss_vps_ed25519",
  "container_match": "shenyu|gateway"
}
```

For a retained local JSON log:

```powershell
python scripts\vps_gateway_logs.py local tmp_gateway_log_84f8b85a.json --detail
```

For VPS container logs:

```powershell
$env:SHENYU_VPS_HOST="root@example.com"
python scripts\vps_gateway_logs.py ssh --list-containers
python scripts\vps_gateway_logs.py ssh --match "shenyu|gateway" --tail 300 -f
```

If public gateway API access is not blocked by Cloudflare, this also works:

```powershell
python scripts\vps_gateway_logs.py api --errors --detail
```

Do not store gateway tokens, SSH host secrets, or API keys in repo files. Ask the user for missing credentials or use environment variables already configured in the shell.

## Log Interpretation

- `tools_offered` means tools were included in the request payload.
- `gateway_tools_executed` means the gateway actually received and ran gateway-native tool calls.
- If `tools_offered > 0` but `gateway_tools_executed = 0`, the failure happened before gateway tool execution. Check upstream, relay, payload shape, streaming, and prompt-cache compatibility first.
- `Max retries reached` from the upstream relay usually means the relay failed before the gateway received a usable model response.
- For OpenAI-compatible relays, `prompt_cache.protocol=openai` with `cache_control` breakpoints is a compatibility suspect if errors only appear with tools/streaming/cache together.

Read `DEBUGGING_GUIDE.md` for the full request flow and deeper triage notes.
