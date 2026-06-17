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
        }
    )

    output = capsys.readouterr().out
    assert "stage=prepare_messages" in output
    assert "last_activity_at=2026-06-17T00:00:01+00:00" in output


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
