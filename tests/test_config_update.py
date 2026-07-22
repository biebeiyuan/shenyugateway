from __future__ import annotations

from fastapi.testclient import TestClient

import gateway
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.runtime import persist_env
from shenyu_gateway.store import GatewayStore


DEFAULTED_ENV_KEYS = [
    "ENABLE_OPENAI_CACHE_CONTROL",
    "ENABLE_ANTHROPIC_CACHE_CONTROL",
    "OPENAI_CACHE_TTL",
    "ANTHROPIC_CACHE_TTL",
    "ENABLE_ANTHROPIC_AUTO_THINKING",
    "ANTHROPIC_AUTO_THINKING_EFFORT",
    "ANTHROPIC_DEFAULT_MAX_TOKENS",
    "UPSTREAM_PROVIDER_ORDER_ENABLED",
    "UPSTREAM_PROVIDER_FORMAT",
    "UPSTREAM_PROVIDER_ORDER",
    "UPSTREAM_EXTRA_BODY",
    "ENABLE_INLINE_MEMORY_CAPTURE",
    "INJECT_INLINE_MEMORY_PROMPT",
    "INJECT_MEM_NOTES",
    "ENABLE_MEM0_MANAGEMENT_TOOLS",
    "MAX_INTERNAL_TOOL_ROUNDS",
    "MAX_CLIENT_MESSAGES",
    "GATEWAY_REQUEST_LOG_RETENTION",
    "ROOM_NEWSPAPER_QA_ENABLED",
    "ROOM_NEWSPAPER_LLM_MODEL",
    "ROOM_NEWSPAPER_LLM_URL",
    "ROOM_NEWSPAPER_LLM_API_KEY",
    "ROOM_NEWSPAPER_LLM_PROTOCOL",
    "STAR_SOFT_DIRECT_COOLDOWN_TURNS",
    "HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS",
]


def _config_client(monkeypatch):
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(gateway.cfg, "gateway_key", "")
    monkeypatch.setattr(gateway, "_persist_env", lambda updates, **kwargs: persisted.append(dict(updates)))
    return TestClient(gateway.app), persisted


def test_runtime_defaults_enable_mem_cache_tools_and_trim(monkeypatch):
    for key in DEFAULTED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    cfg = RuntimeConfig()

    assert cfg.enable_openai_cache_control is True
    assert cfg.enable_anthropic_cache_control is True
    assert cfg.openai_cache_ttl == "5m"
    assert cfg.anthropic_cache_ttl == "1h"
    assert cfg.enable_anthropic_auto_thinking is False
    assert cfg.anthropic_auto_thinking_effort == ""
    assert cfg.anthropic_default_max_tokens == 128000
    assert cfg.upstream_extra_body == {}
    assert cfg.inject_inline_memory_prompt is True
    assert cfg.enable_inline_memory_capture is True
    assert cfg.inject_mem_notes is True
    assert cfg.enable_mem0_management_tools is True
    assert cfg.max_internal_tool_rounds == 15
    assert cfg.max_client_messages == 75
    assert cfg.gateway_request_log_retention == 200
    assert cfg.room_newspaper_qa_enabled is False
    assert cfg.room_newspaper_llm_model == ""
    assert cfg.star_soft_direct_cooldown_turns == 8
    assert cfg.heartbeat_archive_reconcile_deletions is False


def test_aggregate_cache_usage_preserves_multi_round_reported_state():
    summary = gateway._aggregate_cache_usage(
        [
            {"prompt_tokens_details": {"cached_tokens": 120}},
            {
                "cache_creation_input_tokens": 80,
                "cache_creation": {"ephemeral_1h_input_tokens": 80},
            },
            {"prompt_tokens": 10},
        ]
    )

    assert summary == {
        "cache_read_input_tokens": 120,
        "cache_creation_input_tokens": 80,
        "cache_creation": {"ephemeral_1h_input_tokens": 80},
        "hit": True,
        "write": True,
        "read_reported": True,
        "write_reported": True,
        "reported": True,
        "rounds": 3,
        "input_tokens": 10,
        "input_reported": False,
        "total_input_tokens": 10,
        "total_input_reported": False,
        "cache_read_percent": None,
        "cache_prefix_reuse_percent": 60.0,
    }


def test_aggregate_cache_usage_uses_normalized_total_for_anthropic_coverage():
    summary = gateway._aggregate_cache_usage(
        [
            {
                "input_tokens": 10,
                "cache_read_input_tokens": 700,
                "cache_creation_input_tokens": 300,
            }
        ],
        protocol="anthropic",
    )

    assert summary["total_input_tokens"] == 1010
    assert summary["cache_read_percent"] == 69.3
    assert summary["cache_prefix_reuse_percent"] == 70.0


def test_full_config_only_hides_supabase_key(monkeypatch):
    client, _persisted = _config_client(monkeypatch)
    visible_secrets = {
        "gateway_key": "gateway-secret",
        "upstream_api_key": "upstream-secret",
        "hisense_api_key": "hisense-secret",
        "calendar_api_key": "calendar-secret",
    }
    for field, value in visible_secrets.items():
        monkeypatch.setattr(gateway.cfg, field, value)
    monkeypatch.setattr(gateway.cfg, "supabase_key", "supabase-secret")
    try:
        response = client.get(
            "/api/config/full",
            headers={"Authorization": "Bearer gateway-secret"},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    for field, value in visible_secrets.items():
        assert payload[field] == value
        assert payload[f"{field}_configured"] is True
    assert payload["supabase_key"] == ""
    assert payload["supabase_key_configured"] is True
    assert "supabase-secret" not in response.text


def test_config_update_response_returns_new_upstream_key(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "upstream_api_key", "old-secret")

    try:
        response = client.post("/api/config", json={"upstream_api_key": "new-secret"})
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["upstream_api_key"] == "new-secret"
    assert payload["config"]["upstream_api_key_configured"] is True
    assert persisted[-1]["ANTHROPIC_API_KEY"] == "new-secret"


def test_blank_max_client_messages_still_means_unlimited(monkeypatch):
    monkeypatch.setenv("MAX_CLIENT_MESSAGES", "")

    cfg = RuntimeConfig()

    assert cfg.max_client_messages is None


def test_legacy_provider_order_migrates_into_extra_body_string(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock", "Amazon Bedrock", "OpenAI"]')

    cfg = RuntimeConfig()

    assert cfg.upstream_extra_body["provider"] == "Amazon Bedrock"


def test_legacy_provider_order_migrates_into_extra_body_order_object(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPSTREAM_PROVIDER_FORMAT", "order_object")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", "Amazon Bedrock, OpenAI")

    cfg = RuntimeConfig()

    assert cfg.upstream_extra_body["provider"] == {"order": ["Amazon Bedrock", "OpenAI"]}


def test_explicit_extra_body_provider_not_overridden_by_legacy_order(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock"]')
    monkeypatch.setenv("UPSTREAM_EXTRA_BODY", '{"provider": "OpenAI"}')

    cfg = RuntimeConfig()

    assert cfg.upstream_extra_body["provider"] == "OpenAI"


def test_legacy_provider_order_not_migrated_when_disabled(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock"]')

    cfg = RuntimeConfig()

    assert "provider" not in cfg.upstream_extra_body


def test_upstream_extra_body_env_accepts_json_object(monkeypatch):
    monkeypatch.setenv("UPSTREAM_EXTRA_BODY", '{"models":["claude-opus-4-7"],"models ":["claude-opus-4-7"]}')

    cfg = RuntimeConfig()

    assert cfg.upstream_extra_body == {
        "models": ["claude-opus-4-7"],
        "models ": ["claude-opus-4-7"],
    }


def test_blank_wake_welcome_message_preserves_existing_value(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "wake_welcome_message", "上一次的欢迎词")
    monkeypatch.setattr(gateway.cfg, "calendar_model", "old-calendar-model")

    try:
        response = client.post(
            "/api/config",
            json={
                "calendar_model": "new-calendar-model",
                "wake_welcome_message": "",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["wake_welcome_message"] == "上一次的欢迎词"
    assert "calendar_model" in payload["changed"]
    assert "wake_welcome_message" not in payload["changed"]
    assert gateway.cfg.wake_welcome_message == "上一次的欢迎词"
    assert all("WAKE_WELCOME_MESSAGE" not in update for update in persisted)


def test_wake_welcome_message_can_be_cleared_explicitly(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "wake_welcome_message", "上一次的欢迎词")

    try:
        response = client.post(
            "/api/config",
            json={"clear_wake_welcome_message": True},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["wake_welcome_message"] == ""
    assert "wake_welcome_message" in payload["changed"]
    assert gateway.cfg.wake_welcome_message == ""
    assert persisted[-1]["WAKE_WELCOME_MESSAGE"] == ""


def test_config_update_saves_provider_via_extra_body(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "upstream_extra_body", {})

    try:
        response = client.post(
            "/api/config",
            json={"upstream_extra_body": {"provider": {"order": ["Amazon Bedrock", "OpenAI"]}}},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["upstream_extra_body"] == {"provider": {"order": ["Amazon Bedrock", "OpenAI"]}}
    assert "upstream_extra_body" in payload["changed"]
    assert gateway.cfg.upstream_extra_body == {"provider": {"order": ["Amazon Bedrock", "OpenAI"]}}
    assert persisted[-1]["UPSTREAM_EXTRA_BODY"] == '{"provider": {"order": ["Amazon Bedrock", "OpenAI"]}}'


def test_config_update_warns_when_extra_body_overrides_core_fields(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "upstream_extra_body", {})

    try:
        response = client.post(
            "/api/config",
            json={"upstream_extra_body": {"model": "override-me", "tools": []}},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert "warnings" in payload
    assert any("model" in w and "tools" in w for w in payload["warnings"])


def test_config_update_saves_upstream_extra_body(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "upstream_extra_body", {})

    try:
        response = client.post(
            "/api/config",
            json={"upstream_extra_body": {"models": ["claude-opus-4-7"], "models ": ["claude-opus-4-7"]}},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["upstream_extra_body"] == {
        "models": ["claude-opus-4-7"],
        "models ": ["claude-opus-4-7"],
    }
    assert "upstream_extra_body" in payload["changed"]
    assert gateway.cfg.upstream_extra_body == {
        "models": ["claude-opus-4-7"],
        "models ": ["claude-opus-4-7"],
    }
    assert persisted[-1]["UPSTREAM_EXTRA_BODY"] == (
        '{"models": ["claude-opus-4-7"], "models ": ["claude-opus-4-7"]}'
    )


def test_config_update_saves_anthropic_auto_thinking(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "enable_anthropic_auto_thinking", False)

    try:
        response = client.post(
            "/api/config",
            json={"enable_anthropic_auto_thinking": True},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["enable_anthropic_auto_thinking"] is True
    assert "enable_anthropic_auto_thinking" in payload["changed"]
    assert gateway.cfg.enable_anthropic_auto_thinking is True
    assert persisted[-1]["ENABLE_ANTHROPIC_AUTO_THINKING"] == "true"


def test_config_update_saves_anthropic_auto_thinking_effort(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "anthropic_auto_thinking_effort", "")

    try:
        response = client.post(
            "/api/config",
            json={"anthropic_auto_thinking_effort": "xhigh"},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["anthropic_auto_thinking_effort"] == "xhigh"
    assert gateway.cfg.anthropic_auto_thinking_effort == "xhigh"
    assert persisted[-1]["ANTHROPIC_AUTO_THINKING_EFFORT"] == "xhigh"


def test_config_update_rejects_unknown_anthropic_auto_thinking_effort(monkeypatch):
    client, _ = _config_client(monkeypatch)

    try:
        response = client.post(
            "/api/config",
            json={"anthropic_auto_thinking_effort": "high"},
        )
    finally:
        client.close()

    assert response.status_code == 400


def test_config_update_saves_anthropic_cache_control(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "enable_anthropic_cache_control", True)

    try:
        response = client.post(
            "/api/config",
            json={"enable_anthropic_cache_control": False},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["enable_anthropic_cache_control"] is False
    assert "enable_anthropic_cache_control" in payload["changed"]
    assert gateway.cfg.enable_anthropic_cache_control is False
    assert persisted[-1]["ENABLE_ANTHROPIC_CACHE_CONTROL"] == "false"


def test_config_update_saves_independent_cache_ttls(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "openai_cache_ttl", "5m")
    monkeypatch.setattr(gateway.cfg, "anthropic_cache_ttl", "1h")

    try:
        response = client.post(
            "/api/config",
            json={"openai_cache_ttl": "1h", "anthropic_cache_ttl": "5m"},
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert gateway.cfg.openai_cache_ttl == "1h"
    assert gateway.cfg.anthropic_cache_ttl == "5m"
    assert persisted[-1]["OPENAI_CACHE_TTL"] == "1h"
    assert persisted[-1]["ANTHROPIC_CACHE_TTL"] == "5m"


def test_config_update_saves_anthropic_default_max_tokens(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "anthropic_default_max_tokens", 128000)

    try:
        response = client.post(
            "/api/config",
            json={"anthropic_default_max_tokens": 64000},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["anthropic_default_max_tokens"] == 64000
    assert "anthropic_default_max_tokens" in payload["changed"]
    assert gateway.cfg.anthropic_default_max_tokens == 64000
    assert persisted[-1]["ANTHROPIC_DEFAULT_MAX_TOKENS"] == 64000


def test_config_update_saves_request_log_retention(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "gateway_request_log_retention", 200)

    try:
        response = client.post(
            "/api/config",
            json={"gateway_request_log_retention": 350},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["gateway_request_log_retention"] == 350
    assert "gateway_request_log_retention" in payload["changed"]
    assert gateway.cfg.gateway_request_log_retention == 350
    assert persisted[-1]["GATEWAY_REQUEST_LOG_RETENTION"] == 350


def test_config_update_saves_and_clamps_star_soft_direct_cooldown(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "star_soft_direct_cooldown_turns", 8)

    try:
        response = client.post(
            "/api/config",
            json={"star_soft_direct_cooldown_turns": 120},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["star_soft_direct_cooldown_turns"] == 100
    assert "star_soft_direct_cooldown_turns" in payload["changed"]
    assert gateway.cfg.star_soft_direct_cooldown_turns == 100
    assert persisted[-1]["STAR_SOFT_DIRECT_COOLDOWN_TURNS"] == 100


def test_persist_env_saves_config_overrides_to_sqlite(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr("shenyu_gateway.runtime.ENV_PATH", env_path)
    for key in ["UPSTREAM_URL", "ENABLE_GATEWAY_TOOLS", "WAKE_WELCOME_MESSAGE"]:
        monkeypatch.delenv(key, raising=False)
    store = GatewayStore(str(tmp_path / "gateway.db"))

    persist_env(
        {
            "UPSTREAM_URL": "https://persisted.example.com",
            "ENABLE_GATEWAY_TOOLS": False,
            "WAKE_WELCOME_MESSAGE": "persist me",
        },
        store=store,
    )

    overrides = store.load_config_overrides()
    assert overrides["UPSTREAM_URL"] == "https://persisted.example.com"
    assert overrides["ENABLE_GATEWAY_TOOLS"] == "false"
    assert overrides["WAKE_WELCOME_MESSAGE"] == "persist me"
    assert "UPSTREAM_URL=https://persisted.example.com" in env_path.read_text(encoding="utf-8")


def test_restore_config_overrides_from_sqlite_feeds_runtime_config(tmp_path, monkeypatch):
    db_path = tmp_path / "gateway.db"
    store = GatewayStore(str(db_path))
    store.save_config_overrides(
        {
            "UPSTREAM_URL": "https://restored.example.com",
            "ENABLE_GATEWAY_TOOLS": "false",
            "MAX_CLIENT_MESSAGES": "",
            "STAR_SOFT_DIRECT_COOLDOWN_TURNS": "12",
        }
    )
    monkeypatch.setenv("UPSTREAM_URL", "https://default.example.com")
    monkeypatch.setenv("ENABLE_GATEWAY_TOOLS", "true")
    monkeypatch.delenv("MAX_CLIENT_MESSAGES", raising=False)
    monkeypatch.setenv("STAR_SOFT_DIRECT_COOLDOWN_TURNS", "8")

    gateway._restore_config_overrides_from_db(str(db_path))
    cfg = RuntimeConfig()

    assert cfg.upstream_url == "https://restored.example.com"
    assert cfg.enable_gateway_tools is False
    assert cfg.max_client_messages is None
    assert cfg.star_soft_direct_cooldown_turns == 12
