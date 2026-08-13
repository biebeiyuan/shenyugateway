#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LIMIT = 30
LOCAL_CONFIG_ENV = "SHENYU_GATEWAY_LOG_CONFIG"
LOCAL_CONFIG_NAME = ".shenyu-gateway-debug.local.json"
HOME_CONFIG_NAME = ".shenyu-gateway-debug.json"
DEFAULT_CONTAINER_MATCH = "shenyu|gateway"


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


def _args_first(args: argparse.Namespace, *names: str) -> str:
    for name in names:
        value = getattr(args, name, None)
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
    headers = {
        "Accept": "application/json",
        "User-Agent": "shenyu-gateway-debug/1.0",
    }
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


def _ssh_control_path() -> str:
    if os.name == "nt":
        return ""
    user_id = str(os.getuid()) if hasattr(os, "getuid") else "user"
    control_dir = Path(tempfile.gettempdir()) / f"shenyu-gateway-ssh-{user_id}"
    control_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    control_dir.chmod(0o700)
    return str(control_dir / "cm-%C")


def _ssh_args(args: argparse.Namespace, config: dict[str, Any], remote: str) -> list[str]:
    explicit_connection = any(
        value is not None and str(value).strip()
        for value in (
            getattr(args, "host", None),
            getattr(args, "user", None),
            getattr(args, "port", None),
            getattr(args, "identity", None),
        )
    )
    alias = (
        getattr(args, "ssh_alias", None)
        or _env_first("SHENYU_VPS_SSH_ALIAS", "VPS_SSH_ALIAS")
        or _config_first(config, "ssh_alias", "vps_ssh_alias")
        or ("vps" if os.name == "nt" and not explicit_connection else "")
    )
    ssh_args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
    ]
    control_path = _ssh_control_path()
    if control_path:
        ssh_args.extend(["-o", f"ControlPath={control_path}"])
    if alias and not explicit_connection:
        return [*ssh_args, str(alias), remote]

    target = _ssh_target(args, config)
    port = args.port or _config_int(config, "vps_port", "ssh_port", "port")
    identity = (
        args.identity
        or _env_first("SHENYU_VPS_IDENTITY", "VPS_IDENTITY")
        or _config_first(config, "vps_identity", "ssh_identity", "identity", "key_path")
    )
    if port:
        ssh_args.extend(["-p", str(port)])
    if identity:
        ssh_args.extend(["-i", identity])
    ssh_args.extend([target, remote])
    return ssh_args


def _looks_like_container_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{4,64}", value.strip()))


def _configured_container(config: dict[str, Any]) -> str:
    return _config_first(
        config,
        "container_name",
        "docker_container_name",
        "container",
        "docker_container",
        "container_id",
        "docker_container_id",
    )


def _container_family_prefix(target: str) -> str:
    if _looks_like_container_id(target):
        return ""
    match = re.fullmatch(r"(.+)-\d{6,}", target.strip())
    return match.group(1) if match else ""


def _container_match(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return _args_first(args, "match") or _config_first(config, "container_match", "match") or DEFAULT_CONTAINER_MATCH


def _container_label(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return _args_first(args, "label") or _config_first(config, "container_label", "docker_label", "label")


def _container_service(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return _args_first(args, "service") or _config_first(config, "service", "compose_service", "container_service")


def _remote_container_exact_lookup(target: str) -> str:
    condition = "$1 == target || $2 == target"
    if _looks_like_container_id(target):
        condition += " || index($1, target) == 1 || index(target, $1) == 1"
    return (
        "docker ps --no-trunc --format '{{.ID}} {{.Names}}' | "
        "awk -v target="
        + sh_quote(target)
        + " '"
        + condition
        + " {print $2; exit}'"
    )


def _remote_container_resolver(args: argparse.Namespace, config: dict[str, Any], *, purpose: str) -> str:
    target_from_args = _args_first(args, "container")
    target = target_from_args or _configured_container(config)
    label = _container_label(args, config)
    service = _container_service(args, config)
    pattern = _container_match(args, config)
    steps = ["name=''"]

    if target:
        steps.append(f"name=$({_remote_container_exact_lookup(target)})")
        steps.append(
            "if [ -z \"$name\" ]; then "
            + "echo '# configured container "
            + sh_quote(target)
            + " is not running; falling back to label/service/match resolution' >&2; "
            + "fi"
        )
        family = _container_family_prefix(target)
        if family:
            steps.append(
                "if [ -z \"$name\" ]; then "
                + "name=$(docker ps --format '{{.Names}}' | awk -v prefix="
                + sh_quote(family + "-")
                + " 'index($1, prefix) == 1 {print $1; exit}'); "
                + "fi"
            )
    if label:
        steps.append(
            "if [ -z \"$name\" ]; then "
            + "name=$(docker ps --filter "
            + sh_quote(f"label={label}")
            + " --format '{{.Names}}' | head -n 1); "
            + "fi"
        )
    if service:
        steps.append(
            "if [ -z \"$name\" ]; then "
            + "name=$(docker ps --filter "
            + sh_quote(f"label=com.docker.compose.service={service}")
            + " --format '{{.Names}}' | head -n 1); "
            + "fi"
        )
    if pattern:
        steps.append(
            "if [ -z \"$name\" ]; then "
            + "name=$(docker ps --format '{{.Names}} {{.Image}} {{.Labels}}' | grep -Ei "
            + sh_quote(pattern)
            + " | awk '{print $1; exit}'); "
            + "fi"
        )
    steps.append(
        "if [ -z \"$name\" ]; then "
        + "for candidate in $(docker ps --format '{{.Names}}'); do "
        + "if docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \"$candidate\" "
        + "| grep -qE '^(GATEWAY_DB_PATH|ENABLE_GATEWAY_TOOLS|SHENYU_CLIENT_NAME)='; then "
        + "name=\"$candidate\"; break; fi; "
        + "done; "
        + "fi"
    )

    steps.append(
        "if [ -z \"$name\" ]; then "
        + f"echo 'No gateway container found for {purpose}. "
        + "Set container_name, container_label, compose_service, or container_match in local config.' >&2; "
        + "docker ps --format 'table {{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}' >&2; "
        + "exit 1; "
        + "fi"
    )
    return "; ".join(steps)


def _remote_gateway_api_command(args: argparse.Namespace, config: dict[str, Any], path: str, timeout: float) -> str:
    resolve_container = _remote_container_resolver(args, config, purpose="gateway API")
    code = (
        "import os, sys, urllib.parse, urllib.request\n"
        "path = sys.argv[1]\n"
        "timeout = float(sys.argv[2])\n"
        "token = os.environ.get('GATEWAY_API_KEY', '')\n"
        "url = 'http://127.0.0.1:8010' + path\n"
        "if token:\n"
        "    sep = '&' if '?' in url else '?'\n"
        "    url += sep + urllib.parse.urlencode({'token': token})\n"
        "request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'shenyu-gateway-debug/1.0'})\n"
        "with urllib.request.urlopen(request, timeout=timeout) as response:\n"
        "    sys.stdout.write(response.read().decode('utf-8'))\n"
    )
    return (
        resolve_container
        + "; "
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


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _timestamp_sort_key(item: dict[str, Any]) -> float:
    parsed = _parse_timestamp(item.get("timestamp"))
    return parsed.timestamp() if parsed is not None else float("-inf")


def _format_gap(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    minutes, remainder = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{remainder:02d}s"


def _cache_ttl_seconds(value: Any) -> int | None:
    ttl = str(value or "").strip().lower()
    if ttl in {"", "default", "5m"}:
        return 5 * 60
    if ttl == "1h":
        return 60 * 60
    return None


def _build_cache_report(logs: list[dict[str, Any]], session_tag: str = "") -> dict[str, Any]:
    selected = [
        item
        for item in logs
        if isinstance(item, dict) and (not session_tag or str(item.get("session_tag") or "") == session_tag)
    ]
    selected.sort(key=_timestamp_sort_key)

    rows: list[dict[str, Any]] = []
    previous_at: datetime | None = None
    previous_fingerprints: dict[str, str] = {}
    for item in selected:
        at = _parse_timestamp(item.get("timestamp"))
        gap_seconds = None
        if at is not None and previous_at is not None:
            try:
                gap_seconds = max(0, int((at - previous_at).total_seconds()))
            except TypeError:
                gap_seconds = None
        if at is not None:
            previous_at = at

        prompt_cache = item.get("prompt_cache") if isinstance(item.get("prompt_cache"), dict) else {}
        cache_usage = item.get("cache_usage") if isinstance(item.get("cache_usage"), dict) else {}
        window = (
            item.get("client_message_window")
            if isinstance(item.get("client_message_window"), dict)
            else {}
        )
        island = item.get("memory_island") if isinstance(item.get("memory_island"), dict) else {}
        star = island.get("star") if isinstance(island.get("star"), dict) else {}
        mem = island.get("mem") if isinstance(island.get("mem"), dict) else {}
        read_tokens = int(cache_usage.get("cache_read_input_tokens") or 0)
        write_tokens = int(cache_usage.get("cache_creation_input_tokens") or 0)
        breakpoints = prompt_cache.get("breakpoints") if isinstance(prompt_cache.get("breakpoints"), list) else []
        fingerprint_items = (
            prompt_cache.get("prefix_fingerprints")
            if isinstance(prompt_cache.get("prefix_fingerprints"), list)
            else []
        )
        prefix_fingerprints = {
            str(entry.get("path")): str(entry.get("sha256"))
            for entry in fingerprint_items
            if isinstance(entry, dict) and entry.get("path") and entry.get("sha256")
        }
        unchanged_prefixes = sorted(
            path
            for path, sha256 in prefix_fingerprints.items()
            if previous_fingerprints.get(path) == sha256
        )
        attempted = bool(prompt_cache.get("enabled") and breakpoints)
        ttl = str(prompt_cache.get("ttl") or "default")
        ttl_seconds = _cache_ttl_seconds(ttl)
        hit = read_tokens > 0
        miss = attempted and not hit and str(item.get("status") or "").lower() == "ok"
        rows.append(
            {
                "timestamp": item.get("timestamp"),
                "local_time": at.astimezone().strftime("%m-%d %H:%M:%S") if at else "?",
                "gap_seconds": gap_seconds,
                "gap": _format_gap(gap_seconds),
                "id": item.get("id"),
                "status": item.get("status"),
                "session_tag": item.get("session_tag"),
                "protocol": prompt_cache.get("protocol"),
                "ttl": ttl,
                "ttl_seconds": ttl_seconds,
                "breakpoints": breakpoints,
                "prefix_fingerprints": prefix_fingerprints,
                "unchanged_prefixes": unchanged_prefixes,
                "tail_guard_user_turns": int(prompt_cache.get("tail_guard_user_turns") or 0),
                "cache_attempted": attempted,
                "cache_hit": hit,
                "cache_miss": miss,
                "cache_read_input_tokens": read_tokens,
                "cache_creation_input_tokens": write_tokens,
                "gap_exceeds_ttl": bool(
                    gap_seconds is not None and ttl_seconds is not None and gap_seconds > ttl_seconds
                ),
                "event_class": window.get("event_class"),
                "epoch_id": window.get("context_epoch_id"),
                "epoch_reset": bool(window.get("context_epoch_reset")),
                "epoch_reset_reason": window.get("context_epoch_reset_reason"),
                "common_prefix_messages": window.get("common_prefix_messages"),
                "strict_common_prefix_messages": window.get("strict_common_prefix_messages"),
                "transient_history_changes_ignored": bool(
                    window.get("transient_history_changes_ignored")
                ),
                "images_seen": int(window.get("client_image_messages_seen") or 0),
                "images_trimmed": int(window.get("client_image_messages_trimmed") or 0),
                "attachments_seen": int(window.get("client_attachment_messages_seen") or 0),
                "attachments_trimmed": int(window.get("client_attachment_messages_trimmed") or 0),
                "island_decision": island.get("decision"),
                "island_changed": bool(island.get("changed")),
                "island_version": item.get("memory_island_version"),
                "star_overlap": star.get("overlap"),
                "mem_overlap": mem.get("overlap"),
            }
        )
        previous_fingerprints = prefix_fingerprints

    misses = [row for row in rows if row["cache_miss"]]
    hits = [row for row in rows if row["cache_hit"]]
    attempts = len(hits) + len(misses)
    summary = {
        "logs": len(rows),
        "hits": len(hits),
        "misses": len(misses),
        "hit_rate": round(len(hits) / attempts, 4) if attempts else 0.0,
        "read_tokens": sum(int(row["cache_read_input_tokens"]) for row in rows),
        "write_tokens": sum(int(row["cache_creation_input_tokens"]) for row in rows),
        "misses_after_ttl": sum(1 for row in misses if row["gap_exceeds_ttl"]),
        "hits_after_ttl": sum(1 for row in hits if row["gap_exceeds_ttl"]),
        "misses_without_reported_write": sum(
            1 for row in misses if int(row["cache_creation_input_tokens"]) == 0
        ),
        "island_rewrites": sum(1 for row in rows if row["island_changed"]),
        "epoch_resets": sum(1 for row in rows if row["epoch_reset"]),
        "misses_with_unchanged_prefix": sum(
            1 for row in misses if row.get("unchanged_prefixes")
        ),
        "branch_resets": sum(
            1 for row in rows if row["epoch_reset_reason"] == "history_branch"
        ),
        "image_requests": sum(1 for row in rows if row["images_seen"] > 0),
    }
    return {"session_tag": session_tag or None, "rows": rows, "summary": summary}


def _print_cache_report(report: dict[str, Any]) -> None:
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    print("# gateway cache report")
    print(f"logs={summary.get('logs', 0)} session={report.get('session_tag') or 'all'}")
    if not rows:
        print("(no request logs in the current gateway process; a recent deploy may have cleared the in-memory log ring)")
    for row in rows:
        if not isinstance(row, dict):
            continue
        cache_status = "HIT" if row.get("cache_hit") else ("MISS" if row.get("cache_miss") else "OFF")
        print(
            f"{row.get('local_time')} gap={row.get('gap')} id={row.get('id')} "
            f"cache={cache_status} read={row.get('cache_read_input_tokens')} "
            f"write={row.get('cache_creation_input_tokens')} ttl={row.get('ttl')}"
        )
        if row.get("prefix_fingerprints"):
            print(
                "  cache_prefixes="
                + " ".join(
                    f"{path}:{sha256[:8]}"
                    for path, sha256 in row["prefix_fingerprints"].items()
                )
            )
        print(
            "  "
            + " ".join(
                [
                    f"event={row.get('event_class')}",
                    f"reset={row.get('epoch_reset_reason') or '-'}",
                    f"island={row.get('island_decision') or '?'}",
                    f"star_overlap={row.get('star_overlap')}",
                    f"images={row.get('images_seen')}/{row.get('images_trimmed')}",
                    f"attachments={row.get('attachments_seen')}/{row.get('attachments_trimmed')}",
                    f"tail_guard={row.get('tail_guard_user_turns')}",
                    f"prefix={row.get('common_prefix_messages')}/{row.get('strict_common_prefix_messages')}",
                    f"breakpoints={len(row.get('breakpoints') or [])}",
                ]
            )
        )

    print(
        "summary: "
        + " | ".join(
            [
                f"hits={summary.get('hits', 0)}",
                f"misses={summary.get('misses', 0)}",
                f"read_tokens={summary.get('read_tokens', 0)}",
                f"write_tokens={summary.get('write_tokens', 0)}",
                f"island_rewrites={summary.get('island_rewrites', 0)}",
                f"epoch_resets={summary.get('epoch_resets', 0)}",
            ]
        )
    )
    findings = []
    if summary.get("misses_after_ttl"):
        findings.append(
            f"{summary['misses_after_ttl']} miss(es) followed gaps longer than the declared TTL."
        )
    if summary.get("hits_after_ttl"):
        findings.append(
            f"{summary['hits_after_ttl']} hit(s) followed gaps longer than the declared TTL; relay/automatic caching is likely involved."
        )
    if summary.get("island_rewrites"):
        findings.append(
            f"Memory island changed on {summary['island_rewrites']} request(s), invalidating island-end prefixes."
        )
    if summary.get("branch_resets"):
        findings.append(f"History branch reset occurred on {summary['branch_resets']} request(s).")
    if summary.get("misses_without_reported_write"):
        findings.append(
            f"{summary['misses_without_reported_write']} miss(es) reported no cache creation tokens; the relay may hide write metadata."
        )
    if summary.get("misses_with_unchanged_prefix"):
        findings.append(
            f"{summary['misses_with_unchanged_prefix']} miss(es) kept at least one identical cache-prefix fingerprint from the previous request; upstream cache routing or retention is suspect."
        )
    if findings:
        print("analysis:")
        for finding in findings:
            print("  - " + finding)


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


def _phase_summary(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    bits = [
        str(item.get("phase") or "?"),
        f"elapsed={item.get('elapsed_ms')}ms",
        f"delta={item.get('delta_ms')}ms",
    ]
    detail = item.get("detail")
    if isinstance(detail, dict) and detail:
        detail_bits = [f"{key}={_shorten(value, 80)}" for key, value in detail.items()]
        bits.append("detail: " + ", ".join(detail_bits))
    return " | ".join(bits)


def _last_phase_name(item: dict[str, Any]) -> str:
    timeline = item.get("timeline") or item.get("timeline_tail")
    if isinstance(timeline, list) and timeline:
        last = timeline[-1]
        if isinstance(last, dict):
            return str(last.get("phase") or "")
    return ""


def _print_timeline(timeline: Any, *, indent: str = "    ") -> None:
    if not isinstance(timeline, list):
        return
    for item in timeline:
        summary = _phase_summary(item)
        if summary:
            print(indent + summary)


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


def _response_evidence_summary(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    upstream = value.get("upstream") if isinstance(value.get("upstream"), dict) else {}
    normalized = value.get("normalized") if isinstance(value.get("normalized"), dict) else {}
    return " | ".join(
        [
            f"mode={value.get('mode')}",
            f"protocol={value.get('protocol')}",
            f"thinking_requested={value.get('thinking_requested')}",
            (
                f"upstream={value.get('upstream_format')}"
                f"(blocks={upstream.get('thinking_blocks', 0)},"
                f"deltas={upstream.get('thinking_deltas', 0)},"
                f"content={upstream.get('thinking_content_seen', False)})"
            ),
            (
                f"normalized={value.get('normalized_format')}"
                f"(blocks={normalized.get('thinking_blocks', 0)},"
                f"deltas={normalized.get('thinking_deltas', 0)},"
                f"content={normalized.get('thinking_content_seen', False)})"
            ),
            f"usage_seen={upstream.get('usage_seen', False)}",
            f"finish_seen={upstream.get('finish_seen', False)}",
        ]
    )


def _print_log_summary(log: dict[str, Any], *, detail: bool = False) -> None:
    status = log.get("status") or "?"
    log_id = log.get("id") or "?"
    request_id = log.get("request_id") or ""
    timestamp = log.get("timestamp") or ""
    stage = log.get("stage") or ""
    last_activity = log.get("last_activity_at") or ""
    model = log.get("client_model") or log.get("model") or "?"
    duration = log.get("duration_ms")
    stream = log.get("stream")
    session = log.get("session_tag")
    tools_count = log.get("tools_count")
    rounds = _round_count(log)
    executed = _tool_execution_count(log)
    finish_reason = log.get("finish_reason")

    head = f"{timestamp}  [{status}]  id={log_id}"
    if request_id:
        head += f" request_id={request_id}"
    print(head)
    stage_bits = []
    if stage:
        stage_bits.append(f"stage={stage}")
    if last_activity:
        stage_bits.append(f"last_activity_at={last_activity}")
    if stage_bits:
        print("  " + " | ".join(stage_bits))
    print(
        "  "
        + " | ".join(
            [
                f"model={model}",
                f"session={session}",
                f"stream={stream}",
                f"duration_ms={duration}",
                f"finish_reason={finish_reason}",
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
        thinking = payload_summary.get("thinking")
        if isinstance(thinking, dict):
            summary_bits.append(
                "thinking="
                + ",".join(
                    f"{key}:{value}"
                    for key, value in thinking.items()
                    if value is not None
                )
            )
        print("  upstream_payload: " + " | ".join(summary_bits))

    prompt_cache = log.get("prompt_cache")
    if isinstance(prompt_cache, dict):
        breakpoints = prompt_cache.get("breakpoints") or []
        if breakpoints:
            print(
                "  prompt_cache: "
                + f"protocol={prompt_cache.get('protocol')} ttl={prompt_cache.get('ttl') or 'default'} "
                + f"breakpoints={', '.join(map(str, breakpoints))}"
            )
        fingerprints = prompt_cache.get("prefix_fingerprints") or []
        if fingerprints:
            print(
                "  cache_prefixes: "
                + ", ".join(
                    f"{item.get('path')}={item.get('sha256')}"
                    for item in fingerprints
                    if isinstance(item, dict)
                )
            )

    response_evidence = _response_evidence_summary(log.get("upstream_response_evidence"))
    if response_evidence:
        print(f"  upstream_response: {response_evidence}")

    names = _tool_names(log.get("tool_names_all") or log.get("tool_names"))
    if names:
        print(f"  tool_names: {names}")

    slow_phases = log.get("slow_phases")
    if isinstance(slow_phases, list) and slow_phases:
        print("  slow_phases:")
        _print_timeline(slow_phases[:5])

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
        timeline = log.get("timeline")
        if isinstance(timeline, list):
            print("  timeline:")
            _print_timeline(timeline)
        _print_detail_sections(log)
    print()


def _print_debug_summary(data: dict[str, Any]) -> None:
    logs = data.get("logs") if isinstance(data.get("logs"), dict) else {}
    http_requests = logs.get("http_requests") if isinstance(logs.get("http_requests"), dict) else {}
    active = http_requests.get("active") if isinstance(http_requests.get("active"), list) else []
    recent = http_requests.get("recent") if isinstance(http_requests.get("recent"), list) else []
    latest = logs.get("latest") if isinstance(logs.get("latest"), dict) else {}
    upstream = data.get("upstream") if isinstance(data.get("upstream"), dict) else {}
    default_upstream = upstream.get("default") if isinstance(upstream.get("default"), dict) else {}

    print("# gateway debug")
    print(f"generated_at={data.get('generated_at')}")
    if default_upstream:
        print(
            "upstream: "
            + " | ".join(
                [
                    f"chat_url={default_upstream.get('chat_url')}",
                    f"protocol={default_upstream.get('protocol')}",
                    f"api_key_configured={default_upstream.get('api_key_configured')}",
                ]
            )
        )
    print(
        "logs: "
        + " | ".join(
            [
                f"count={logs.get('count')}",
                f"capacity={logs.get('capacity')}",
            ]
        )
    )
    if latest:
        print(
            "latest_log: "
            + " | ".join(
                [
                    f"id={latest.get('id')}",
                    f"request_id={latest.get('request_id')}",
                    f"status={latest.get('status')}",
                    f"stage={latest.get('stage')}",
                    f"finish_reason={latest.get('finish_reason')}",
                    f"last_activity_at={latest.get('last_activity_at')}",
                    f"duration_ms={latest.get('duration_ms')}",
                ]
            )
        )
    print(f"active_http_requests={len(active)} recent_http_requests={len(recent)}")
    for item in active[:10]:
        if not isinstance(item, dict):
            continue
        phase = _last_phase_name(item)
        print(
            "  active: "
            + " | ".join(
                [
                    f"request_id={item.get('request_id')}",
                    f"session={item.get('session_tag')}",
                    f"client={item.get('client_name')}",
                    f"started_at={item.get('started_at')}",
                    f"last_activity_at={item.get('last_activity_at')}",
                    f"duration_ms={item.get('duration_ms')}",
                    f"phase={phase}",
                ]
            )
        )
    for item in recent[:5]:
        if not isinstance(item, dict):
            continue
        phase = _last_phase_name(item)
        print(
            "  recent: "
            + " | ".join(
                [
                    f"request_id={item.get('request_id')}",
                    f"status={item.get('status')}",
                    f"http_status={item.get('http_status')}",
                    f"session={item.get('session_tag')}",
                    f"duration_ms={item.get('duration_ms')}",
                    f"phase={phase}",
                ]
            )
        )


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
                + f"stream={item.get('stream')} final={item.get('final')} "
                + f"finish_reason={item.get('finish_reason')}"
            )
            thinking = item.get("anthropic_thinking")
            if isinstance(thinking, dict) and thinking.get("preserved"):
                print(
                    "      "
                    + f"anthropic_thinking blocks={thinking.get('blocks')} "
                    + f"signature={thinking.get('signature_present')} "
                    + f"redacted={thinking.get('redacted_present')}"
                )
            response_evidence = _response_evidence_summary(item.get("upstream_response_evidence"))
            if response_evidence:
                print(f"      upstream_response: {response_evidence}")
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

    memory_island = log.get("memory_island")
    if isinstance(memory_island, dict) and memory_island:
        print("  memory_island: " + _json_dumps(memory_island))

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
            _print_debug_summary(data)
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


def command_cache(args: argparse.Namespace) -> int:
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
    path = f"/api/gateway/logs?limit={max(1, min(int(args.limit or 12), 200))}"
    if args.via_ssh:
        data = _http_json_via_ssh(args, config, path, timeout=args.timeout)
    else:
        data = _http_json(base_url, path, token=token, timeout=args.timeout)
    report = _build_cache_report(_iter_log_objects(data), session_tag=args.session or "")
    if args.json_output:
        print(_json_dumps(report))
    else:
        _print_cache_report(report)
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
        return "docker ps --format 'table {{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'"
    container = args.container or _configured_container(config)
    label = _container_label(args, config)
    if container or label:
        resolve_container = _remote_container_resolver(args, config, purpose="docker logs")
        return resolve_container + "; echo \"# docker logs $name\"; " + f"docker logs --tail {tail}{follow} \"$name\""
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

    resolve_container = _remote_container_resolver(args, config, purpose="docker logs")
    return resolve_container + "; echo \"# docker logs $name\"; " + f"docker logs --tail {tail}{follow} \"$name\""


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
    api.add_argument("--container", help="Container name/id candidate for --via-ssh. Falls back if it is no longer running.")
    api.add_argument("--match", help="Regex used to auto-pick a running container for --via-ssh.")
    api.add_argument("--label", help="Docker label used to auto-pick a running container for --via-ssh.")
    api.add_argument("--service", help="Docker compose service name used to auto-pick a running container for --via-ssh.")
    api.add_argument("--host", help="SSH host for --via-ssh. Defaults to local config.")
    api.add_argument("--user", help="SSH user for --via-ssh. Defaults to local config.")
    api.add_argument("--port", type=int, help="SSH port for --via-ssh. Defaults to local config.")
    api.add_argument("--identity", help="SSH identity file for --via-ssh. Defaults to local config.")
    api.add_argument("--ssh-alias", help="SSH config alias; on Windows this project defaults to 'vps'.")
    api.set_defaults(func=command_api)

    cache = subparsers.add_parser("cache", help="Pull recent logs and print a cache/epoch/image timeline.")
    cache.add_argument("--config", help=f"Local JSON config. Env: {LOCAL_CONFIG_ENV}.")
    cache.add_argument("--url", help="Gateway base URL for --direct mode.")
    cache.add_argument("--token", help="Gateway token for --direct mode.")
    cache.add_argument("--limit", type=int, default=12)
    cache.add_argument("--session", help="Only analyze one session_tag.")
    cache.add_argument("--timeout", type=float, default=20.0)
    cache.add_argument(
        "--direct",
        dest="via_ssh",
        action="store_false",
        help="Use the public gateway API instead of SSH.",
    )
    cache.add_argument(
        "--container",
        help="Container name/id candidate. Stale Coolify names fall back by app prefix.",
    )
    cache.add_argument("--match", help="Regex used to auto-pick a running container.")
    cache.add_argument("--label", help="Docker label used to auto-pick a running container.")
    cache.add_argument("--service", help="Docker compose service used to auto-pick a running container.")
    cache.add_argument("--host", help="SSH host. Defaults to local config.")
    cache.add_argument("--user", help="SSH user. Defaults to local config.")
    cache.add_argument("--port", type=int, help="SSH port. Defaults to local config.")
    cache.add_argument("--identity", help="SSH identity file. Defaults to local config.")
    cache.add_argument(
        "--ssh-alias",
        help="SSH config alias; on Windows this project defaults to 'vps'.",
    )
    cache.add_argument("--json", dest="json_output", action="store_true", help="Print structured JSON.")
    cache.set_defaults(func=command_cache, via_ssh=True)

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
    ssh.add_argument("--ssh-alias", help="SSH config alias; on Windows this project defaults to 'vps'.")
    ssh.add_argument("--tail", type=int, default=200)
    ssh.add_argument("--follow", "-f", action="store_true")
    ssh.add_argument("--container", help="Docker container name/id candidate to tail. Falls back if it is no longer running.")
    ssh.add_argument("--match", help="Regex used to auto-pick a running container. Default: shenyu|gateway.")
    ssh.add_argument("--label", help="Docker label used to auto-pick a running container.")
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
