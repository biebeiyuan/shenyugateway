from __future__ import annotations

from fastapi.testclient import TestClient

import gateway
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.runtime import persist_env
from shenyu_gateway.store import GatewayStore


DEFAULTED_ENV_KEYS = [
    "ENABLE_OPENAI_CACHE_CONTROL",
    "ENABLE_ANTHROPIC_AUTO_THINKING",
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
    assert cfg.enable_anthropic_auto_thinking is False
    assert cfg.anthropic_default_max_tokens == 128000
    assert cfg.upstream_extra_body == {}
    assert cfg.inject_inline_memory_prompt is True
    assert cfg.enable_inline_memory_capture is True
    assert cfg.inject_mem_notes is True
    assert cfg.enable_mem0_management_tools is True
    assert cfg.max_internal_tool_rounds == 15
    assert cfg.max_client_messages == 75


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
        }
    )
    monkeypatch.setenv("UPSTREAM_URL", "https://default.example.com")
    monkeypatch.setenv("ENABLE_GATEWAY_TOOLS", "true")
    monkeypatch.delenv("MAX_CLIENT_MESSAGES", raising=False)

    gateway._restore_config_overrides_from_db(str(db_path))
    cfg = RuntimeConfig()

    assert cfg.upstream_url == "https://restored.example.com"
    assert cfg.enable_gateway_tools is False
    assert cfg.max_client_messages is None
