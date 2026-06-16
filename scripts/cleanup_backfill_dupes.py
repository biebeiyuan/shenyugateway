"""One-shot script: soft-delete backfill duplicate rows in shenyu_chat_archive.

Run with SUPABASE_URL and SUPABASE_SERVICE_KEY configured, for example:

    python scripts/cleanup_backfill_dupes.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BAD_EVENT = "2026-06-09T12:46:26.595526+00:00"
BAD_ARCHIVED = "2026-06-14T10:01:00.074115+00:00"


def _load_env_file() -> None:
    path = ".env"
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _supabase_config() -> tuple[str, dict[str, str]]:
    _load_env_file()
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not base_url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured.")
    table_url = f"{base_url}/rest/v1/shenyu_chat_archive"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    return table_url, headers


def fetch_all(qs: str) -> list:
    url, headers = _supabase_config()
    rows: list = []
    off = 0
    while True:
        req = urllib.request.Request(url + qs + f"&limit=1000&offset={off}", headers=headers)
        data = json.loads(urllib.request.urlopen(req).read())
        rows.extend(data)
        if len(data) < 1000:
            break
        off += 1000
    return rows


def main() -> None:
    url, headers = _supabase_config()
    bad_event_enc = BAD_EVENT.replace("+", "%2B")
    bad_archived_enc = BAD_ARCHIVED.replace("+", "%2B")

    bad = fetch_all(
        f"?select=id,content_hash&deleted_at=is.null"
        f"&event_at=eq.{bad_event_enc}"
        f"&archived_at=eq.{bad_archived_enc}"
    )
    bad_hashes = {r["content_hash"] for r in bad}
    print(f"Bad rows: {len(bad)}, unique hashes: {len(bad_hashes)}")

    good = fetch_all(
        f"?select=content_hash&deleted_at=is.null"
        f"&not.and=(event_at.eq.{bad_event_enc}"
        f",archived_at.eq.{bad_archived_enc})"
    )
    good_hashes = {r["content_hash"] for r in good}
    overlap = bad_hashes & good_hashes
    print(f"Good unique hashes: {len(good_hashes)}, overlap: {len(overlap)}")

    ids = [r["id"] for r in bad if r["content_hash"] in overlap]
    print(f"IDs to soft-delete: {len(ids)}")

    if not ids:
        print("Nothing to delete.")
        return

    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        qs = "?id=in.(" + ",".join(batch) + ")"
        body = json.dumps({"deleted_at": now}).encode()
        req = urllib.request.Request(
            url + qs,
            data=body,
            method="PATCH",
            headers={**headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        urllib.request.urlopen(req)
        print(f"  deleted {min(i + 50, len(ids))}/{len(ids)}")

    req = urllib.request.Request(
        url + "?select=id&deleted_at=is.null&limit=1",
        headers={**headers, "Prefer": "count=exact"},
    )
    resp = urllib.request.urlopen(req)
    print(f"After cleanup: {resp.headers.get('Content-Range', '')}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        raise
