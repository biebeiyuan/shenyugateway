import argparse
from scripts import vps_gateway_logs as logs


def _args(**overrides):
    values = {
        "container": None,
        "match": None,
        "label": None,
        "service": None,
        "list_containers": False,
        "remote_command": None,
        "tail": 200,
        "follow": False,
        "cwd": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_configured_container_id_is_resolved_before_logs_command():
    remote = logs._remote_command(
        _args(),
        {"container": "abc123def456", "container_match": "shenyu|gateway"},
    )

    assert "docker ps --no-trunc --format '{{.ID}} {{.Names}}'" in remote
    assert "index($1, target) == 1 || index(target, $1) == 1" in remote
    assert "falling back to label/service/match resolution" in remote
    assert "grep -Ei 'shenyu|gateway'" in remote
    assert 'docker logs --tail 200 "$name"' in remote
    assert "docker logs --tail 200 'abc123def456'" not in remote


def test_gateway_api_via_ssh_resolves_container_name_each_time():
    remote = logs._remote_gateway_api_command(
        _args(),
        {"container_name": "shenyu-gateway-1"},
        "/api/gateway/logs?limit=1",
        30.0,
    )

    assert "docker ps --no-trunc --format '{{.ID}} {{.Names}}'" in remote
    assert "awk -v target='shenyu-gateway-1'" in remote
    assert 'docker exec "$name" python -c' in remote
    assert "docker exec 'shenyu-gateway-1'" not in remote


def test_stale_coolify_container_uses_app_prefix_before_slow_inspection():
    remote = logs._remote_gateway_api_command(
        _args(),
        {"container_name": "gyed0diy0bxr2w4lts73f1tb-165346192694"},
        "/api/gateway/logs?limit=1",
        20.0,
    )

    family_lookup = "awk -v prefix='gyed0diy0bxr2w4lts73f1tb-'"
    env_inspection = "for candidate in $(docker ps --format '{{.Names}}')"
    assert family_lookup in remote
    assert remote.index(family_lookup) < remote.index(env_inspection)


def test_container_label_takes_priority_before_regex_match():
    remote = logs._remote_command(
        _args(label="com.docker.compose.project=shenyu"),
        {"container_match": "gateway"},
    )

    label_lookup = "docker ps --filter 'label=com.docker.compose.project=shenyu'"
    match_lookup = "grep -Ei 'gateway'"
    assert label_lookup in remote
    assert match_lookup in remote
    assert remote.index(label_lookup) < remote.index(match_lookup)


def test_log_summary_prints_stage_and_last_activity(capsys):
    logs._print_log_summary(
        {
            "id": "abc123",
            "request_id": "req123",
            "timestamp": "2026-06-17T00:00:00+00:00",
            "stage": "prepare_messages",
            "last_activity_at": "2026-06-17T00:00:01+00:00",
            "status": "preparing",
            "client_model": "test-model",
            "stream": True,
            "session_tag": "test-session",
            "duration_ms": 1000,
            "tools_count": 0,
            "slow_phases": [
                {"phase": "prepare.client_messages_trimmed", "elapsed_ms": 900, "delta_ms": 500}
            ],
        }
    )

    output = capsys.readouterr().out
    assert "stage=prepare_messages" in output
    assert "last_activity_at=2026-06-17T00:00:01+00:00" in output
    assert "slow_phases:" in output
    assert "prepare.client_messages_trimmed" in output


def test_cache_report_identifies_ttl_and_relay_anomalies(capsys):
    report = logs._build_cache_report(
        [
            {
                "id": "one",
                "timestamp": "2026-07-10T16:00:00+00:00",
                "status": "ok",
                "session_tag": "6.20",
                "prompt_cache": {
                    "enabled": True,
                    "protocol": "anthropic",
                    "ttl": "5m",
                    "breakpoints": ["system.end"],
                    "tail_guard_user_turns": 3,
                },
                "cache_usage": {
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 0,
                },
                "client_message_window": {
                    "event_class": "new_user",
                    "client_attachment_messages_seen": 4,
                    "client_attachment_messages_trimmed": 1,
                },
                "memory_island": {"changed": False, "decision": "retained"},
            },
            {
                "id": "two",
                "timestamp": "2026-07-10T16:08:00+00:00",
                "status": "ok",
                "session_tag": "6.20",
                "prompt_cache": {
                    "enabled": True,
                    "protocol": "anthropic",
                    "ttl": "5m",
                    "breakpoints": ["system.end"],
                },
                "cache_usage": {
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "client_message_window": {
                    "event_class": "new_user",
                    "client_image_messages_seen": 1,
                },
                "memory_island": {
                    "changed": True,
                    "decision": "rewritten",
                    "star": {"overlap": 0.6667},
                },
            },
            {
                "id": "three",
                "timestamp": "2026-07-10T17:18:00+00:00",
                "status": "ok",
                "session_tag": "6.20",
                "prompt_cache": {
                    "enabled": True,
                    "protocol": "anthropic",
                    "ttl": "5m",
                    "breakpoints": ["system.end"],
                },
                "cache_usage": {
                    "cache_read_input_tokens": 900,
                    "cache_creation_input_tokens": 0,
                },
                "client_message_window": {"event_class": "new_user"},
                "memory_island": {"changed": False, "decision": "retained"},
            },
        ],
        session_tag="6.20",
    )

    assert report["summary"]["misses_after_ttl"] == 1
    assert report["summary"]["hits_after_ttl"] == 1
    assert report["summary"]["misses_without_reported_write"] == 1
    assert report["summary"]["island_rewrites"] == 1

    logs._print_cache_report(report)
    output = capsys.readouterr().out
    assert "cache=MISS" in output
    assert "tail_guard=3" in output
    assert "attachments=4/1" in output
    assert "relay/automatic caching is likely involved" in output


def test_cache_parser_defaults_to_ssh():
    args = logs.build_parser().parse_args(["cache"])

    assert args.via_ssh is True
    assert args.limit == 12


def test_debug_summary_prints_active_http_requests(capsys):
    logs._print_debug_summary(
        {
            "ok": True,
            "logs": {
                "latest": {
                    "id": "log1",
                    "request_id": "req1",
                    "status": "preparing",
                    "stage": "prepare_messages",
                    "last_activity_at": "2026-06-17T00:00:01+00:00",
                    "duration_ms": 1000,
                },
                "http_requests": {
                    "active": [
                        {
                            "request_id": "req1",
                            "session_tag": "test-session",
                            "client_name": "operit",
                            "started_at": "2026-06-17T00:00:00+00:00",
                            "last_activity_at": "2026-06-17T00:00:01+00:00",
                            "duration_ms": 0,
                            "timeline": [
                                {"phase": "http.entry", "elapsed_ms": 0, "delta_ms": 0},
                                {"phase": "handler.entered", "elapsed_ms": 1000, "delta_ms": 1000},
                            ],
                        }
                    ],
                    "recent": [],
                },
            },
        }
    )

    output = capsys.readouterr().out
    assert "# gateway debug" in output
    assert "active_http_requests=1" in output
    assert "active: request_id=req1" in output
    assert "phase=handler.entered" in output
