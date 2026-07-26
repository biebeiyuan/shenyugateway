from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import gateway
from shenyu_gateway.store import GatewayStore


class FakeSupabaseClient:
    def __init__(self, calendar_pages: list[dict]):
        self.calendar_pages = calendar_pages

    async def query(self, table: str, params: dict | None = None) -> list[dict]:
        if table != "calendar_pages":
            return []
        params = params or {}
        rows = list(self.calendar_pages)
        id_filter = params.get("id")
        if isinstance(id_filter, str) and id_filter.startswith("eq."):
            expected_id = id_filter.removeprefix("eq.")
            rows = [row for row in rows if row.get("id") == expected_id]
        return [dict(row) for row in rows]


@pytest.fixture()
def external_contract_client(monkeypatch, tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    normal_session = store.get_or_create_session("main", "operit")
    hisense_session = store.get_or_create_session("hisense", "hisense")
    store.append_heartbeat(normal_session["id"], "normal heartbeat")
    store.append_heartbeat(hisense_session["id"], "hisense heartbeat", hisense=True)

    calendar_pages = [
        {
            "id": "page_day_1",
            "period_type": "day",
            "period_key": "2026-05-18",
            "period_start": "2026-05-18T00:00:00+00:00",
            "period_end": "2026-05-19T00:00:00+00:00",
            "version": 1,
            "is_latest": True,
            "title": "Day title",
            "summary": "Day summary",
            "content": "Full day content",
            "digest": "Day digest",
            "status": "final",
            "created_at": "2026-05-18T01:00:00+00:00",
            "updated_at": "2026-05-18T01:00:00+00:00",
        }
    ]

    monkeypatch.setattr(gateway, "session_store", store)
    monkeypatch.setattr(gateway, "supabase_client", FakeSupabaseClient(calendar_pages))
    monkeypatch.setattr(gateway.cfg, "gateway_key", "secret")

    client = TestClient(gateway.app)
    try:
        yield client
    finally:
        client.close()


def test_query_token_auth_allows_external_heartbeat_reads(external_contract_client):
    normal = external_contract_client.get(
        "/api/gateway/heartbeats?token=secret&limit=2000&order=asc&scope=normal"
    )
    hisense = external_contract_client.get(
        "/api/gateway/heartbeats?token=secret&limit=2000&order=asc&scope=hisense"
    )

    assert normal.status_code == 200
    assert hisense.status_code == 200

    normal_payload = normal.json()
    hisense_payload = hisense.json()

    assert normal_payload["scope"] == "normal"
    assert hisense_payload["scope"] == "hisense"
    assert [item["content"] for item in normal_payload["heartbeats"]] == ["normal heartbeat"]
    assert [item["content"] for item in hisense_payload["heartbeats"]] == ["hisense heartbeat"]
    assert normal_payload["heartbeats"][0]["created_at"][:10]
    assert hisense_payload["heartbeats"][0]["created_at"][:10]


def test_options_preflight_is_not_blocked_by_api_auth(external_contract_client):
    response = external_contract_client.options(
        "/api/calendar/month",
        headers={
            "Origin": "https://home.yuanuwuclaude.uk",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code != 401
    assert response.headers.get("access-control-allow-origin") == "https://home.yuanuwuclaude.uk"


def test_calendar_month_contract_for_home_frontend(external_contract_client):
    response = external_contract_client.get("/api/calendar/month?token=secret&month=2026-05")

    assert response.status_code == 200
    payload = response.json()
    day = next(item for item in payload["grid"] if item["date"] == "2026-05-18")

    assert day["day"] == 18
    assert day["in_month"] is True
    assert day["has_day"] is True
    assert "has_week" in day
    assert day["day_page"] == {
        "id": "page_day_1",
        "title": "Day title",
        "summary": "Day summary",
        "status": "final",
    }


def test_calendar_page_contract_for_home_frontend(external_contract_client):
    response = external_contract_client.get("/api/calendar/page/page_day_1?token=secret")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "page_day_1"
    assert payload["title"] == "Day title"
    assert payload["summary"] == "Day summary"
    assert payload["content"] == "Full day content"


def test_chat_client_is_login_gated_but_installability_assets_stay_public(external_contract_client):
    page = external_contract_client.get("/chat", headers={"Accept": "text/html"})
    assert page.status_code == 401
    assert "管理密钥" in page.text

    external_contract_client.cookies.set("shenyu_token", "secret")
    with_cookie = external_contract_client.get("/chat", headers={"Accept": "text/html"})
    assert with_cookie.status_code != 401

    external_contract_client.cookies.delete("shenyu_token")
    manifest = external_contract_client.get("/chat/manifest.webmanifest")
    assert manifest.status_code != 401
    icon = external_contract_client.get("/chat/icon.svg")
    assert icon.status_code != 401
