from __future__ import annotations

from fastapi.testclient import TestClient

import gateway
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.runtime import persist_env
from shenyu_gateway.store import GatewayStore


DEFAULTED_ENV_KEYS = [
    "ENABLE_OPENAI_CACHE_CONTROL",
    "UPSTREAM_PROVIDER_ORDER_ENABLED",
    "UPSTREAM_PROVIDER_FORMAT",
    "UPSTREAM_PROVIDER_ORDER",
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
    assert cfg.upstream_provider_order_enabled is False
    assert cfg.upstream_provider_format == "string"
    assert cfg.upstream_provider_order == []
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


def test_provider_order_env_accepts_json_and_dedupes(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", '["Amazon Bedrock", "Amazon Bedrock", "OpenAI"]')

    cfg = RuntimeConfig()

    assert cfg.upstream_provider_order == ["Amazon Bedrock", "OpenAI"]


def test_provider_order_env_accepts_comma_list(monkeypatch):
    monkeypatch.setenv("UPSTREAM_PROVIDER_ORDER", "Amazon Bedrock, OpenAI")

    cfg = RuntimeConfig()

    assert cfg.upstream_provider_order == ["Amazon Bedrock", "OpenAI"]


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


def test_config_update_saves_provider_order(monkeypatch):
    client, persisted = _config_client(monkeypatch)
    monkeypatch.setattr(gateway.cfg, "upstream_provider_order_enabled", False)
    monkeypatch.setattr(gateway.cfg, "upstream_provider_format", "string")
    monkeypatch.setattr(gateway.cfg, "upstream_provider_order", [])

    try:
        response = client.post(
            "/api/config",
            json={
                "upstream_provider_order_enabled": True,
                "upstream_provider_format": "order_object",
                "upstream_provider_order": ["Amazon Bedrock", "Amazon Bedrock", "OpenAI"],
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["upstream_provider_order_enabled"] is True
    assert payload["config"]["upstream_provider_format"] == "order_object"
    assert payload["config"]["upstream_provider_order"] == ["Amazon Bedrock", "OpenAI"]
    assert "upstream_provider_order_enabled" in payload["changed"]
    assert "upstream_provider_format" in payload["changed"]
    assert "upstream_provider_order" in payload["changed"]
    assert persisted[-1]["UPSTREAM_PROVIDER_ORDER_ENABLED"] == "true"
    assert persisted[-1]["UPSTREAM_PROVIDER_FORMAT"] == "order_object"
    assert persisted[-1]["UPSTREAM_PROVIDER_ORDER"] == '["Amazon Bedrock", "OpenAI"]'


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
