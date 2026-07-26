from __future__ import annotations

"""Heartbeat disaster-recovery backup into Supabase.

The SQLite heartbeat pool stays the live read path. This service copies rows
into the Supabase `shenyu_heartbeat_archive` table after a settle window, so
manual cleanup (re-roll duplicates, runaway heartbeats) done in SQLite before
the window closes never reaches the archive. Optional deletion reconciliation
is kept behind an explicit production guard because it treats one SQLite store
as the authority for remote archive visibility.
"""

from typing import Any, Optional

from .runtime import iso_now, logger

ARCHIVE_TABLE = "shenyu_heartbeat_archive"

# The archive table keeps a scope column (CHECK constraint admits it); only the
# normal pool is written since the hisense pool was removed.
_SCOPE = "normal"


class HeartbeatArchiveService:
    def __init__(self, store: Any, supabase: Any, cfg: Any):
        self.store = store
        self.supabase = supabase
        self.cfg = cfg

    def _settle_hours(self) -> int:
        return max(int(getattr(self.cfg, "heartbeat_archive_settle_hours", 6) or 6), 0)

    def _batch_size(self) -> int:
        return max(1, min(int(getattr(self.cfg, "heartbeat_archive_batch_size", 200) or 200), 1000))

    def _reconcile_deletions_enabled(self) -> bool:
        return bool(getattr(self.cfg, "heartbeat_archive_reconcile_deletions", False))

    async def run_once(self) -> dict[str, Any]:
        result: dict[str, Any] = {"archived": 0, "soft_deleted": 0, "errors": []}
        if not self.supabase or not self.store:
            return result
        try:
            result["archived"] += await self._sync_settled()
        except Exception as exc:
            result["errors"].append(f"sync {_SCOPE}: {exc}")
        try:
            result["soft_deleted"] += await self._reconcile_deleted()
        except Exception as exc:
            result["errors"].append(f"reconcile {_SCOPE}: {exc}")
        return result

    async def _sync_settled(self) -> int:
        rows = self.store.get_settled_unsynced_heartbeats(
            settle_hours=self._settle_hours(),
            limit=self._batch_size(),
        )
        if not rows:
            return 0
        payload = [
            {
                "id": row["id"],
                "scope": _SCOPE,
                "session_id": row.get("session_id"),
                "content": row.get("content") or "",
                "turn_number": int(row.get("turn_number") or 0),
                "created_at": row.get("created_at"),
                "deleted_at": None,
            }
            for row in rows
            if (row.get("content") or "").strip()
        ]
        if payload:
            await self.supabase.upsert(ARCHIVE_TABLE, payload, on_conflict="id")
        self.store.mark_heartbeats_synced([row["id"] for row in rows])
        return len(payload)

    async def _reconcile_deleted(self) -> int:
        """Soft-delete archive rows whose SQLite source row was removed after archiving."""
        if not self._reconcile_deletions_enabled():
            return 0
        archived = await self.supabase.query(
            ARCHIVE_TABLE,
            params={"select": "id", "scope": f"eq.{_SCOPE}", "deleted_at": "is.null", "limit": "10000"},
        )
        archived_ids = {str(row.get("id")) for row in archived or [] if row.get("id")}
        if not archived_ids:
            return 0
        live_ids = self.store.get_all_heartbeat_ids()
        if not live_ids:
            raise RuntimeError(
                f"refusing to reconcile {len(archived_ids)} {_SCOPE} archive rows "
                "against an empty local heartbeat pool"
            )
        missing = sorted(archived_ids - live_ids)
        if not missing:
            return 0
        # PostgREST in-filter has URL length limits; chunk conservatively.
        marked = 0
        for start in range(0, len(missing), 50):
            chunk = missing[start : start + 50]
            await self.supabase.update(
                ARCHIVE_TABLE,
                {"id": f"in.({','.join(chunk)})", "deleted_at": "is.null"},
                {"deleted_at": iso_now()},
            )
            marked += len(chunk)
        return marked


async def heartbeat_archive_worker(service: HeartbeatArchiveService, interval_seconds: int):
    import asyncio

    interval = max(int(interval_seconds or 600), 60)
    logger.info(
        "[HeartbeatArchiveWorker] started interval=%ss settle_hours=%s reconcile_deletions=%s",
        interval,
        service._settle_hours(),
        service._reconcile_deletions_enabled(),
    )
    try:
        while True:
            try:
                result = await service.run_once()
                if result.get("archived") or result.get("soft_deleted") or result.get("errors"):
                    logger.info("[HeartbeatArchiveWorker] result=%s", result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[HeartbeatArchiveWorker] pass failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("[HeartbeatArchiveWorker] stopped")
        raise
