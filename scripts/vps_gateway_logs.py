#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_LIMIT = 30
LOCAL_CONFIG_ENV = "SHENYU_GATEWAY_LOG_CONFIG"
LOCAL_CONFIG_NAME = ".shenyu-gateway-debug.local.json"
HOME_CONFIG_NAME = ".shenyu-gateway-debug.json"


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not reconfigure:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _shorten(value: Any, limit: int = 240) -> str:
    text = "" if value is None else str(value).replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def _read_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_local_config(path: str = "") -> dict[str, Any]:
    candidates: list[Path] = []
    configured = path or os.getenv(LOCAL_CONFIG_ENV, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(_repo_root() / LOCAL_CONFIG_NAME)
    candidates.append(Path.home() / HOME_CONFIG_NAME)

    for candidate in candidates:
        try:
            if candidate.is_file():
                data = _read_json_file(candidate)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            raise SystemExit(f"Could not read local config {candidate}: {exc}") from exc
    return {}


def _config_first(config: dict[str, Any], *names: str) -> str:
    for name in names:
        value = config.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _config_int(config: dict[str, Any], *names: str) -> int | None:
    value = _config_first(config, *names)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        url = "http://localhost:8010"
    if not re.match(r"^https?://", url):
        url = "https://" + url
    return url.rstrip("/")


def _with_token(url: str, token: str) -> str:
    if not token:
        return url
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == "token" for key, _ in query):
        query.append(("token", token))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def _redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [
        (key, "<redacted>" if key.lower() in {"token", "key", "api_key", "authorization"} else value)
        for key, value in query
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(redacted),
            parsed.fragment,
        )
    )


def _http_json(base_url: str, path: str, token: str = "", timeout: float = 30.0) -> Any:
    target = _with_token(_normalize_base_url(base_url) + path, token)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(target, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {_redact_url(target)}: {_shorten(body, 800)}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {_redact_url(target)}: {exc}") from exc
    return json.loads(raw.decode("utf-8"))


def _ssh_args(args: argparse.Namespace, config: dict[str, Any], remote: str) -> list[str]:
    target = _ssh_target(args, config)
    port = args.port or _config_int(config, "vps_port", "ssh_port", "port")
    identity = (
        args.identity
        or _env_first("SHENYU_VPS_IDENTITY", "VPS_IDENTITY")
        or _config_first(config, "vps_identity", "ssh_identity", "identity", "key_path")
    )
    ssh_args = ["ssh"]
    if port:
        ssh_args.extend(["-p", str(port)])
    if identity:
        ssh_args.extend(["-i", identity])
    ssh_args.extend([target, remote])
    return ssh_args


def _remote_gateway_api_command(args: argparse.Namespace, config: dict[str, Any], path: str, timeout: float) -> str:
    container = (
        getattr(args, "container", None)
        or _config_first(config, "container", "docker_container")
    )
    if container:
        resolve_container = f"name={sh_quote(container)}"
    else:
        pattern = _config_first(config, "container_match", "match") or "shenyu|gateway"
        resolve_container = (
            "name=$(docker ps --format '{{.Names}}' | grep -Ei "
            + sh_quote(pattern)
            + " | head -n 1)"
        )
    code = (
        "import os, sys, urllib.parse, urllib.request\n"
        "path = sys.argv[1]\n"
        "timeout = float(sys.argv[2])\n"
        "token = os.environ.get('GATEWAY_API_KEY', '')\n"
        "url = 'http://127.0.0.1:8010' + path\n"
        "if token:\n"
        "    sep = '&' if '?' in url else '?'\n"
        "    url += sep + urllib.parse.urlencode({'token': token})\n"
        "request = urllib.request.Request(url, headers={'Accept': 'application/json'})\n"
        "with urllib.request.urlopen(request, timeout=timeout) as response:\n"
        "    sys.stdout.write(response.read().decode('utf-8'))\n"
    )
    return (
        resolve_container
        + "; "
        + "if [ -z \"$name\" ]; then "
        + "echo 'No gateway container found. Set container or container_match in local config.' >&2; "
        + "docker ps --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}' >&2; "
        + "exit 1; "
        + "fi; "
        + "docker exec \"$name\" python -c "
        + sh_quote(code)
        + " "
        + sh_quote(path)
        + " "
        + sh_quote(str(timeout))
    )


def _http_json_via_ssh(args: argparse.Namespace, config: dict[str, Any], path: str, timeout: float = 30.0) -> Any:
    remote = _remote_gateway_api_command(args, config, path, timeout)
    ssh_args = _ssh_args(args, config, remote)
    completed = subprocess.run(
        ssh_args,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(10.0, timeout + 15.0),
    )
    if completed.returncode != 0:
        stderr = _shorten(completed.stderr or completed.stdout, 1000)
        raise SystemExit(f"SSH gateway API request failed: {stderr}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"SSH gateway API returned non-JSON output: {_shorten(completed.stdout, 1000)}") from exc


def _iter_log_objects(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("logs"), list):
        return [item for item in data["logs"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _find_log(data: Any, log_id: str) -> dict[str, Any] | None:
    for item in _iter_log_objects(data):
        if str(item.get("id") or "") == log_id or str(item.get("request_id") or "") == log_id:
            return item
    return None


def _tool_execution_count(log: dict[str, Any]) -> int:
    rounds = log.get("internal_tool_rounds")
    if isinstance(rounds, int):
        return 0
    if not isinstance(rounds, list):
        return 0
    count = 0
    for item in rounds:
        if not isinstance(item, dict):
            continue
        tools = item.get("tools") or []
        if isinstance(tools, list):
            count += len(tools)
    return count


def _round_count(log: dict[str, Any]) -> int:
    rounds = log.get("internal_tool_rounds")
    if isinstance(rounds, int):
        return rounds
    if isinstance(rounds, list):
        return len(rounds)
    return 0


def _tool_names(value: Any, limit: int = 12) -> str:
    if not isinstance(value, list):
        return ""
    names = [str(item) for item in value if item]
    if len(names) > limit:
        return ", ".join(names[:limit]) + f", ... (+{len(names) - limit})"
    return ", ".join(names)


def _cache_control_hint(log: dict[str, Any]) -> str:
    prompt_cache = log.get("prompt_cache") if isinstance(log.get("prompt_cache"), dict) else {}
    protocol = str(prompt_cache.get("protocol") or "").lower()
    breakpoints = prompt_cache.get("breakpoints") or []
    if protocol == "openai" and breakpoints:
        return (
            "OpenAI-compatible payload contains cache_control breakpoints. "
            "If the relay does not support Claude cache passthrough, try disabling cache_control for this relay."
        )
    return ""


def _error_hint(log: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    error = str(log.get("error") or "")
    if "Max retries reached" in error:
        hints.append(
            "The upstream relay retried and failed before the gateway received a model response."
        )
    if log.get("status") == "error" and _tool_execution_count(log) == 0 and (log.get("tools_count") or 0):
        hints.append(
            "Tools were offered to the model, but no gateway tool execution is recorded."
        )
    cache_hint = _cache_control_hint(log)
    if cache_hint:
        hints.append(cache_hint)
    return hints


def _print_log_summary(log: dict[str, Any], *, detail: bool = False) -> None:
    status = log.get("status") or "?"
    log_id = log.get("id") or "?"
    request_id = log.get("request_id") or ""
    timestamp = log.get("timestamp") or ""
    model = log.get("client_model") or log.get("model") or "?"
    duration = log.get("duration_ms")
    stream = log.get("stream")
    session = log.get("session_tag")
    tools_count = log.get("tools_count")
    rounds = _round_count(log)
    executed = _tool_execution_count(log)

    head = f"{timestamp}  [{status}]  id={log_id}"
    if request_id:
        head += f" request_id={request_id}"
    print(head)
    print(
        "  "
        + " | ".join(
            [
                f"model={model}",
                f"session={session}",
                f"stream={stream}",
                f"duration_ms={duration}",
            ]
        )
    )
    print(f"  tools_offered={tools_count} internal_rounds={rounds} gateway_tools_executed={executed}")

    payload_summary = log.get("upstream_payload_summary")
    if isinstance(payload_summary, dict):
        summary_bits = [
            f"upstream_model={payload_summary.get('model')}",
            f"messages={payload_summary.get('messages_count')}",
            f"tools={payload_summary.get('tools_count')}",
            f"max_tokens={payload_summary.get('max_tokens')}",
            f"stream={payload_summary.get('stream')}",
        ]
        print("  upstream_payload: " + " | ".join(summary_bits))

    prompt_cache = log.get("prompt_cache")
    if isinstance(prompt_cache, dict):
        breakpoints = prompt_cache.get("breakpoints") or []
        if breakpoints:
            print(
                "  prompt_cache: "
                + f"protocol={prompt_cache.get('protocol')} breakpoints={', '.join(map(str, breakpoints))}"
            )

    names = _tool_names(log.get("tool_names_all") or log.get("tool_names"))
    if names:
        print(f"  tool_names: {names}")

    error = log.get("error")
    if error:
        print(f"  error: {_shorten(error, 700)}")

    response = log.get("response_preview") or log.get("response_full")
    if response:
        print(f"  response: {_shorten(response, 500)}")

    hints = _error_hint(log)
    for hint in hints:
        print(f"  hint: {hint}")

    if detail:
        _print_detail_sections(log)
    print()


def _print_detail_sections(log: dict[str, Any]) -> None:
    rounds = log.get("internal_tool_rounds")
    if isinstance(rounds, list):
        print("  internal_tool_rounds:")
        if not rounds:
            print("    (none)")
        for item in rounds:
            if not isinstance(item, dict):
                continue
            print(
                "    "
                + f"round={item.get('round')} messages={item.get('messages_count')} "
                + f"stream={item.get('stream')} final={item.get('final')}"
            )
            for call in item.get("tools") or []:
                if isinstance(call, dict):
                    print(
                        "      "
                        + f"tool={call.get('name')} cached={call.get('cached_duplicate')} "
                        + f"args={_shorten(call.get('args_preview'), 260)}"
                    )
            returned = item.get("returned_tool_calls") or item.get("gateway_tool_calls") or []
            if returned:
                for call in returned:
                    if isinstance(call, dict):
                        print(
                            "      "
                            + f"returned_tool={call.get('name')} args={_shorten(call.get('arguments_preview'), 260)}"
                        )

    client_window = log.get("client_message_window")
    if isinstance(client_window, dict):
        print("  client_message_window: " + _json_dumps(client_window))

    cold_start = log.get("cold_start")
    if isinstance(cold_start, dict):
        print("  cold_start: " + _json_dumps(cold_start))

    cache_layers = log.get("cache_layers")
    if isinstance(cache_layers, dict):
        print("  cache_layers: " + _json_dumps(cache_layers))

    upstream_payload = log.get("upstream_payload")
    if isinstance(upstream_payload, dict):
        messages = upstream_payload.get("messages") or []
        print("  upstream_payload_messages:")
        if isinstance(messages, list):
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    continue
                as_json = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
                content = message.get("content")
                if isinstance(content, list):
                    preview = _shorten(json.dumps(content, ensure_ascii=False), 180)
                else:
                    preview = _shorten(content, 180)
                print(
                    "    "
                    + f"{index:02d} role={message.get('role')} chars={len(as_json)} "
                    + f"cache_control={'cache_control' in as_json} preview={preview}"
                )


def _print_logs(logs: list[dict[str, Any]], *, errors_only: bool = False, detail: bool = False) -> None:
    filtered = [
        item
        for item in logs
        if not errors_only or str(item.get("status") or "").lower() == "error"
    ]
    if not filtered:
        print("(no matching logs)")
        return
    for item in filtered:
        _print_log_summary(item, detail=detail)


def command_api(args: argparse.Namespace) -> int:
    config = _load_local_config(args.config)
    base_url = (
        args.url
        or _env_first("SHENYU_GATEWAY_URL", "GATEWAY_BASE_URL", "GATEWAY_URL")
        or _config_first(config, "gateway_url", "base_url", "url")
    )
    token = (
        args.token
        or _env_first("SHENYU_GATEWAY_TOKEN", "GATEWAY_API_KEY", "GATEWAY_TOKEN")
        or _config_first(config, "gateway_token", "token", "gateway_api_key")
    )

    def read_api(path: str) -> Any:
        if args.via_ssh:
            return _http_json_via_ssh(args, config, path, timeout=args.timeout)
        return _http_json(base_url, path, token=token, timeout=args.timeout)

    if args.debug:
        data = read_api("/api/gateway/debug")
        if args.raw:
            print(_json_dumps(data))
        else:
            print(_json_dumps(data))
        return 0

    if args.log_id:
        data = read_api("/api/gateway/logs/" + urllib.parse.quote(args.log_id, safe=""))
        if args.raw:
            print(_json_dumps(data))
        else:
            _print_log_summary(data, detail=True)
        if args.save:
            _save_log(data, args.save)
        return 0

    seen: set[str] = set()
    while True:
        data = read_api(f"/api/gateway/logs?limit={args.limit}")
        logs = _iter_log_objects(data)
        if args.raw:
            print(_json_dumps(data))
        elif args.watch:
            new_logs = []
            for item in reversed(logs):
                key = str(item.get("id") or item.get("request_id") or json.dumps(item, sort_keys=True))
                if key not in seen:
                    seen.add(key)
                    new_logs.append(item)
            if new_logs:
                _print_logs(new_logs, errors_only=args.errors, detail=args.detail)
        else:
            _print_logs(logs, errors_only=args.errors, detail=args.detail)

        if not args.watch:
            break
        time.sleep(args.interval)
    return 0


def _save_log(data: dict[str, Any], directory: str) -> None:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = str(data.get("id") or data.get("request_id") or int(time.time()))
    path = target_dir / f"gateway_log_{name}.json"
    path.write_text(_json_dumps(data) + "\n", encoding="utf-8")
    print(f"saved: {path}")


def command_local(args: argparse.Namespace) -> int:
    items: list[dict[str, Any]] = []
    for raw_path in args.paths:
        data = _read_json_file(Path(raw_path))
        if args.log_id:
            found = _find_log(data, args.log_id)
            if found:
                items.append(found)
        else:
            items.extend(_iter_log_objects(data))

    if args.raw:
        if len(items) == 1:
            print(_json_dumps(items[0]))
        else:
            print(_json_dumps({"logs": items}))
        return 0

    _print_logs(items, errors_only=args.errors, detail=args.detail or bool(args.log_id))
    return 0


def _ssh_target(args: argparse.Namespace, config: dict[str, Any]) -> str:
    host = (
        args.host
        or _env_first("SHENYU_VPS_HOST", "VPS_HOST")
        or _config_first(config, "vps_host", "ssh_host", "host")
    )
    user = (
        args.user
        or _env_first("SHENYU_VPS_USER", "VPS_USER")
        or _config_first(config, "vps_user", "ssh_user", "user")
    )
    if not host:
        raise SystemExit("Missing --host or SHENYU_VPS_HOST.")
    if "@" in host or not user:
        return host
    return f"{user}@{host}"


def _remote_command(args: argparse.Namespace, config: dict[str, Any]) -> str:
    tail = max(1, int(args.tail))
    follow = " -f" if args.follow else ""
    if args.remote_command:
        return args.remote_command
    if args.list_containers:
        return "docker ps --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'"
    container = args.container or _config_first(config, "container", "docker_container")
    if container:
        return f"docker logs --tail {tail}{follow} {sh_quote(container)}"
    service = args.service or _config_first(config, "service", "compose_service")
    if service:
        base = f"docker compose logs --tail {tail}"
        if args.follow:
            base += " --follow"
        base += " " + sh_quote(service)
        cwd = args.cwd or _config_first(config, "cwd", "compose_cwd")
        if cwd:
            return f"cd {sh_quote(cwd)} && {base}"
        return base

    pattern = args.match or _config_first(config, "container_match", "match") or "shenyu|gateway"
    return (
        "name=$(docker ps --format '{{.Names}}' | grep -Ei "
        + sh_quote(pattern)
        + " | head -n 1); "
        + "if [ -z \"$name\" ]; then "
        + "echo 'No matching container. Use --list-containers or --container NAME.'; "
        + "docker ps --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}'; "
        + "exit 1; "
        + "fi; "
        + "echo \"# docker logs $name\"; "
        + f"docker logs --tail {tail}{follow} \"$name\""
    )


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def command_ssh(args: argparse.Namespace) -> int:
    config = _load_local_config(args.config)
    remote = _remote_command(args, config)
    ssh_args = _ssh_args(args, config, remote)
    print("# " + " ".join(ssh_args), file=sys.stderr)
    if args.follow:
        process = subprocess.Popen(ssh_args)
        return process.wait()
    completed = subprocess.run(ssh_args, text=True)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect Shenyu gateway request logs locally, through the gateway API, or through SSH."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    api = subparsers.add_parser("api", help="Read /api/gateway/logs from a running gateway.")
    api.add_argument("--config", help=f"Local JSON config. Env: {LOCAL_CONFIG_ENV}.")
    api.add_argument("--url", help="Gateway base URL. Env: SHENYU_GATEWAY_URL, GATEWAY_BASE_URL, GATEWAY_URL.")
    api.add_argument("--token", help="Gateway token. Env: SHENYU_GATEWAY_TOKEN, GATEWAY_API_KEY, GATEWAY_TOKEN.")
    api.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    api.add_argument("--id", dest="log_id", help="Fetch one log by log id or request id.")
    api.add_argument("--errors", action="store_true", help="Only show error logs.")
    api.add_argument("--detail", action="store_true", help="Show detailed sections.")
    api.add_argument("--debug", action="store_true", help="Read /api/gateway/debug instead of request logs.")
    api.add_argument("--raw", action="store_true", help="Print raw JSON.")
    api.add_argument("--save", help="Save one fetched log JSON into this directory.")
    api.add_argument("--watch", action="store_true", help="Poll for new logs.")
    api.add_argument("--interval", type=float, default=3.0)
    api.add_argument("--timeout", type=float, default=30.0)
    api.add_argument("--via-ssh", action="store_true", help="Read gateway API from inside the configured VPS/container.")
    api.add_argument("--container", help="Container name/id for --via-ssh. Defaults to local config.")
    api.add_argument("--host", help="SSH host for --via-ssh. Defaults to local config.")
    api.add_argument("--user", help="SSH user for --via-ssh. Defaults to local config.")
    api.add_argument("--port", type=int, help="SSH port for --via-ssh. Defaults to local config.")
    api.add_argument("--identity", help="SSH identity file for --via-ssh. Defaults to local config.")
    api.set_defaults(func=command_api)

    local = subparsers.add_parser("local", help="Read retained gateway log JSON files.")
    local.add_argument("paths", nargs="+", help="JSON files, for example tmp_gateway_log_84f8b85a.json.")
    local.add_argument("--id", dest="log_id", help="Pick one log by log id or request id.")
    local.add_argument("--errors", action="store_true", help="Only show error logs.")
    local.add_argument("--detail", action="store_true", help="Show detailed sections.")
    local.add_argument("--raw", action="store_true", help="Print raw JSON.")
    local.set_defaults(func=command_local)

    ssh = subparsers.add_parser("ssh", help="Tail Docker or docker compose logs on the VPS.")
    ssh.add_argument("--config", help=f"Local JSON config. Env: {LOCAL_CONFIG_ENV}.")
    ssh.add_argument("--host", help="SSH host or user@host. Env: SHENYU_VPS_HOST, VPS_HOST.")
    ssh.add_argument("--user", help="SSH user. Env: SHENYU_VPS_USER, VPS_USER.")
    ssh.add_argument("--port", type=int)
    ssh.add_argument("--identity", help="SSH identity file.")
    ssh.add_argument("--tail", type=int, default=200)
    ssh.add_argument("--follow", "-f", action="store_true")
    ssh.add_argument("--container", help="Docker container name/id to tail.")
    ssh.add_argument("--match", help="Regex used to auto-pick a running container. Default: shenyu|gateway.")
    ssh.add_argument("--service", help="docker compose service name to tail.")
    ssh.add_argument("--cwd", help="Remote compose directory, used with --service.")
    ssh.add_argument("--list-containers", action="store_true")
    ssh.add_argument("--command", dest="remote_command", help="Run an explicit remote log command through SSH.")
    ssh.set_defaults(func=command_ssh)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
