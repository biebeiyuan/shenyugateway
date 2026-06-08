from __future__ import annotations

from fastapi.testclient import TestClient

import gateway
from shenyu_gateway.config import RuntimeConfig


DEFAULTED_ENV_KEYS = [
    "ENABLE_OPENAI_CACHE_CONTROL",
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
    monkeypatch.setattr(gateway, "_persist_env", lambda updates: persisted.append(dict(updates)))
    return TestClient(gateway.app), persisted


def test_runtime_defaults_enable_mem_cache_tools_and_trim(monkeypatch):
    for key in DEFAULTED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    cfg = RuntimeConfig()

    assert cfg.enable_openai_cache_control is True
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
