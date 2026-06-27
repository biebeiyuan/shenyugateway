from __future__ import annotations
import json
from datetime import timedelta
from typing import Any, Optional
from ..runtime import dt_to_iso, iso_now, json_dumps, now, parse_ts


class CacheMixin:
    def cache_get(self, key: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cache_entries WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            expires_at = parse_ts(row["expires_at"])
            if expires_at and expires_at < now():
                conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
                return None
            return {
                "cache_key": row["cache_key"],
                "cache_type": row["cache_type"],
                "payload": json.loads(row["payload_json"]),
                "expires_at": row["expires_at"],
            }

    def cache_set(self, key: str, cache_type: str, payload: Any, ttl_minutes: int):
        expires_at = now() + timedelta(minutes=ttl_minutes)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entries (
                    cache_key, cache_type, payload_json, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    cache_type = excluded.cache_type,
                    payload_json = excluded.payload_json,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at
                """,
                (key, cache_type, json_dumps(payload), dt_to_iso(expires_at), iso_now()),
            )
