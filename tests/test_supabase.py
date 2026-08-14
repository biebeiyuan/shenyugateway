from __future__ import annotations

import asyncio

from shenyu_gateway.supabase import SupabaseClient


class _SuccessfulResponse:
    def raise_for_status(self):
        return None


def test_upsert_minimal_requests_no_row_representation():
    client = SupabaseClient("https://example.invalid", "test-key")
    captured = {}

    async def request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured.update(kwargs)
        return _SuccessfulResponse()

    client._request = request

    asyncio.run(client.upsert_minimal("example_table", [{"value": 1}], on_conflict="value"))

    assert captured["method"] == "POST"
    assert captured["params"] == {"on_conflict": "value"}
    assert captured["headers"]["Prefer"] == "resolution=merge-duplicates,return=minimal"
