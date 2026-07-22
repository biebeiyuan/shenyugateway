from __future__ import annotations

from pathlib import Path

from scripts.admin_preview import isolated_preview_env


def test_isolated_preview_disables_real_data_and_background_workers(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://real.example")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "real-secret")
    monkeypatch.setenv("ENABLE_HEARTBEAT_ARCHIVE", "true")

    env = isolated_preview_env(port=18123, db_path=Path("/tmp/preview-test.db"))

    assert env["PYTHON_DOTENV_DISABLED"] == "1"
    assert env["PORT"] == "18123"
    assert env["GATEWAY_DB_PATH"] == "/tmp/preview-test.db"
    assert env["SUPABASE_URL"] == ""
    assert env["SUPABASE_SERVICE_KEY"] == ""
    assert env["ENABLE_HEARTBEAT_ARCHIVE"] == "false"
    assert env["HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS"] == "false"
    assert env["ENABLE_RECALL_SYNC_WORKER"] == "false"
