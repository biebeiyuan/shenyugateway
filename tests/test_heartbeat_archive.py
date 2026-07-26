from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.heartbeat_archive import ARCHIVE_TABLE, HeartbeatArchiveService


class FakeStore:
    def __init__(self, *, unsettled: list[dict] | None = None, live_ids: set[str] | None = None):
        self.unsettled = unsettled or []
        self.live_ids = live_ids or set()
        self.marked: list[list[str]] = []

    def get_settled_unsynced_heartbeats(self, **_kwargs):
        return list(self.unsettled)

    def mark_heartbeats_synced(self, heartbeat_ids):
        self.marked.append(list(heartbeat_ids))

    def get_all_heartbeat_ids(self):
        return set(self.live_ids)


class FakeSupabase:
    def __init__(self, archived_ids: set[str] | None = None):
        self.archived_ids = archived_ids or set()
        self.queries: list[tuple[str, dict]] = []
        self.upserts: list[tuple[str, list[dict], str]] = []
        self.updates: list[tuple[str, dict, dict]] = []

    async def query(self, table, params):
        # _reconcile_deleted still filters on the archive table's scope column
        # ("scope": "eq.normal"); the fake answers the same rows for it.
        self.queries.append((table, dict(params)))
        return [{"id": value} for value in sorted(self.archived_ids)]

    async def upsert(self, table, payload, *, on_conflict):
        self.upserts.append((table, list(payload), on_conflict))
        return payload

    async def update(self, table, match, payload):
        self.updates.append((table, dict(match), dict(payload)))
        return []


def _cfg(*, reconcile: bool = False):
    return SimpleNamespace(
        heartbeat_archive_settle_hours=6,
        heartbeat_archive_batch_size=200,
        heartbeat_archive_reconcile_deletions=reconcile,
    )


def test_archive_upload_stays_enabled_when_deletion_reconciliation_is_off():
    row = {
        "id": "hb-new",
        "session_id": "main",
        "content": "settled heartbeat",
        "turn_number": 3,
        "created_at": "2026-07-22T08:00:00+00:00",
    }
    store = FakeStore(unsettled=[row])
    supabase = FakeSupabase(archived_ids={"hb-remote"})

    result = asyncio.run(HeartbeatArchiveService(store, supabase, _cfg()).run_once())

    assert result == {"archived": 1, "soft_deleted": 0, "errors": []}
    assert len(supabase.upserts) == 1
    assert all(item[0] == ARCHIVE_TABLE for item in supabase.upserts)
    assert supabase.queries == []
    assert supabase.updates == []


def test_enabled_reconciliation_refuses_an_empty_local_pool():
    supabase = FakeSupabase(archived_ids={"hb-remote"})
    service = HeartbeatArchiveService(FakeStore(), supabase, _cfg(reconcile=True))

    result = asyncio.run(service.run_once())

    assert result["soft_deleted"] == 0
    assert len(result["errors"]) == 1
    assert all("empty local heartbeat pool" in error for error in result["errors"])
    assert supabase.updates == []


def test_enabled_reconciliation_soft_deletes_only_missing_ids():
    store = FakeStore(live_ids={"hb-live"})
    supabase = FakeSupabase(archived_ids={"hb-live", "hb-missing"})
    service = HeartbeatArchiveService(store, supabase, _cfg(reconcile=True))

    result = asyncio.run(service.run_once())

    assert result["soft_deleted"] == 1
    assert result["errors"] == []
    assert len(supabase.updates) == 1
    assert all(update[1]["id"] == "in.(hb-missing)" for update in supabase.updates)
