from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.config_routes import ConfigRouteDeps, build_config_router
from shenyu_gateway.context_builder import ContextBuilder
from shenyu_gateway.context_layers import render_layered_additions
from shenyu_gateway import runtime
from shenyu_gateway.store import GatewayStore


PROMPT = "只用于测试的回响提示词。\n保留第二行。"


def config_app(cfg, persist):
    app = FastAPI()
    app.include_router(build_config_router(ConfigRouteDeps(
        cfg=cfg,
        validate_http_url=lambda _name, value, **kwargs: value,
        validate_protocol=lambda _name, value, **kwargs: value,
        clamp=lambda value, minimum, maximum: max(minimum, min(value, maximum)),
        persist_env=persist,
        get_supabase_client=lambda: None,
        init_supabase=lambda: None,
        init_store=lambda: None,
        make_upstream_http_client=lambda: None,
    )))
    return app


def builder_for(cfg):
    return ContextBuilder(
        None, None, None,
        cfg=cfg,
        supabase_client=None,
        stable_charter_block=lambda: "",
    )


def test_echo_toggle_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("ENABLE_ECHO", raising=False)
    cfg = RuntimeConfig()
    assert getattr(cfg, "enable_echo", None) is True
    assert cfg.to_dict().get("enable_echo") is True


@pytest.mark.parametrize("value, expected", [("false", False), ("0", False), ("true", True), ("1", True)])
def test_echo_toggle_reads_environment(monkeypatch, value, expected):
    monkeypatch.setenv("ENABLE_ECHO", value)
    cfg = RuntimeConfig()
    assert getattr(cfg, "enable_echo", None) is expected
    assert cfg.to_dict().get("enable_echo") is expected


def test_echo_toggle_saves_without_erasing_prompt_or_retention():
    cfg = RuntimeConfig()
    cfg.enable_echo = True
    cfg.echo_prompt = PROMPT
    cfg.echo_retention_turns = 4
    persisted = []
    with TestClient(config_app(cfg, lambda updates: persisted.append(dict(updates)))) as client:
        for enabled in (False, True):
            response = client.post("/api/config", json={"enable_echo": enabled})
            assert response.status_code == 200
            payload = response.json()
            assert payload["changed"] == ["enable_echo"]
            assert persisted[-1] == {"ENABLE_ECHO": str(enabled).lower()}
            for config in (payload["config"], client.get("/api/config/full").json(), client.get("/api/config").json()):
                assert config.get("enable_echo") is enabled
                assert config["echo_prompt"] == PROMPT
                assert config["echo_retention_turns"] == 4


def test_echo_toggle_omitted_or_null_preserves_disabled_state():
    cfg = RuntimeConfig()
    cfg.enable_echo = False
    cfg.echo_prompt = PROMPT
    persisted = []
    with TestClient(config_app(cfg, lambda updates: persisted.append(dict(updates)))) as client:
        for patch in ({}, {"enable_echo": None}, {"echo_retention_turns": 2}):
            response = client.post("/api/config", json=patch)
            assert response.status_code == 200
            assert response.json()["config"].get("enable_echo") is False
            assert response.json()["config"]["echo_prompt"] == PROMPT
            assert "ENABLE_ECHO" not in persisted[-1]


def test_echo_toggle_rejects_invalid_boolean_without_mutation():
    cfg = RuntimeConfig()
    cfg.enable_echo = False
    cfg.echo_prompt = PROMPT
    persisted = []
    with TestClient(config_app(cfg, lambda updates: persisted.append(dict(updates)))) as client:
        response = client.post("/api/config", json={"enable_echo": "not-a-boolean"})
    assert response.status_code == 422
    assert cfg.enable_echo is False
    assert cfg.echo_prompt == PROMPT
    assert persisted == []


def test_echo_toggle_disabled_omits_only_echo_instructions():
    cfg = RuntimeConfig()
    cfg.echo_prompt = PROMPT
    cfg.echo_retention_turns = 4
    builder = builder_for(cfg)
    package = {"stable_charter": "测试用固定文本"}
    cfg.enable_echo = True
    on_settings = builder._layer_settings()
    on_layers = render_layered_additions(package, on_settings)
    cfg.enable_echo = False
    off_settings = builder._layer_settings()
    off_layers = render_layered_additions(package, off_settings)
    assert off_settings.echo_prompt == ""
    assert off_layers["format"] == off_settings.heartbeat_prompt.rstrip()
    assert on_layers["format"] == PROMPT + "\n\n" + on_settings.heartbeat_prompt.rstrip()
    assert {key: value for key, value in on_layers.items() if key != "format"} == {
        key: value for key, value in off_layers.items() if key != "format"
    }
    assert cfg.echo_prompt == PROMPT
    assert cfg.echo_retention_turns == 4
    cfg.enable_echo = True
    assert builder._layer_settings().echo_prompt == PROMPT


def test_echo_toggle_keeps_empty_prompt_disabled_and_legacy_settings_compatible():
    cfg = RuntimeConfig()
    cfg.enable_echo = True
    cfg.echo_prompt = ""
    assert builder_for(cfg)._layer_settings().echo_prompt == ""
    legacy = SimpleNamespace(echo_prompt=PROMPT)
    assert builder_for(legacy)._layer_settings().echo_prompt == PROMPT


def test_echo_toggle_restores_from_sqlite_after_environment_is_replaced(monkeypatch, tmp_path):
    import gateway

    monkeypatch.setattr(runtime, "ENV_PATH", tmp_path / ".env")
    for key in ("ENABLE_ECHO", "ECHO_PROMPT", "ECHO_RETENTION_TURNS"):
        monkeypatch.setenv(key, "")
    db_path = tmp_path / "gateway.db"
    store = GatewayStore(str(db_path))
    cfg = RuntimeConfig()
    cfg.enable_echo = True
    app = config_app(cfg, lambda updates: runtime.persist_env(updates, store=store))
    with TestClient(app) as client:
        for enabled in (False, True):
            response = client.post("/api/config", json={
                "enable_echo": enabled,
                "echo_prompt": PROMPT,
                "echo_retention_turns": 4,
            })
            assert response.status_code == 200
            assert store.load_config_overrides().get("ENABLE_ECHO") == str(enabled).lower()
            assert f"ENABLE_ECHO={str(enabled).lower()}" in runtime.ENV_PATH.read_text(encoding="utf-8")
            monkeypatch.setenv("ENABLE_ECHO", str(not enabled).lower())
            monkeypatch.setenv("ECHO_PROMPT", "容器环境中的其他文本")
            monkeypatch.setenv("ECHO_RETENTION_TURNS", "1")
            gateway._restore_config_overrides_from_db(str(db_path))
            restored = RuntimeConfig()
            assert getattr(restored, "enable_echo", None) is enabled
            assert restored.echo_prompt == PROMPT
            assert restored.echo_retention_turns == 4
