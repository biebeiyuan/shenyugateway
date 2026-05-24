from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.mem_notes import MemNoteService


class FakeSupabase:
    def __init__(self):
        self.queries = []
        self.updates = []

    async def query(self, table: str, params: dict):
        self.queries.append({"table": table, "params": params})
        if params.get("id") == "eq.88eb939b-8742-4e17-8186-3de6a3e9a016":
            return [
                {
                    "id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
                    "content": "note",
                    "status": "captured",
                    "trigger_keywords": [],
                }
            ]
        return []

    async def update(self, table: str, match: dict, data: dict):
        self.updates.append({"table": table, "match": match, "data": data})
        return [{"id": match["id"], **data}]


def test_update_note_normalizes_uuid_from_pasted_text():
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.update_note(
            "id: 88eb939b-8742-4e17-8186-3de6a3e9a016.",
            {"review_note": "checked"},
        )
    )

    assert result["ok"] is True
    assert result["note_id"] == "88eb939b-8742-4e17-8186-3de6a3e9a016"
    assert supabase.queries[0]["params"]["id"] == "eq.88eb939b-8742-4e17-8186-3de6a3e9a016"
    assert supabase.updates[0]["match"] == {"id": "88eb939b-8742-4e17-8186-3de6a3e9a016"}
