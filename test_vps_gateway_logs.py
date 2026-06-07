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
