from __future__ import annotations

import hashlib
import base64
import json
import uuid
from typing import Any, Optional

from ..runtime import iso_now
from ..album_media import MAX_MEDIA_ITEMS, clean_media, photo_reference

# 沈予的相册。跟聊天里随手发的图是两回事：聊天图只留最近 30 张、过期就清；
# 相册是他自己挑出来放进去的，不限张数、不会过期。
#
# 图片字节存本机卷的 SQLite（生产是 named volume `shenyu-gateway-data` 挂在
# `/data`），不占 Supabase 额度。他写的备注另有一份在 Supabase，那份才进 Recall
# ——所以万一卷出事，丢的是图，他自己写的话还在。

DEFAULT_ALBUM_NAME = "想留的"

# 单张上限。压到长边 1280 / 质量 0.8 大约 300KB，2MB 够留余量又不至于让
# 一张图把库撑大。
MAX_PHOTO_BYTES = 2 * 1024 * 1024


def photo_fingerprint(raw: bytes) -> str:
    """图片字节的稳定指纹，过期回填时用它认出这张图。"""
    return hashlib.sha256(raw).hexdigest()


class AlbumMixin:
    def _album_book_row(self, conn: Any, name: str) -> Optional[dict]:
        row = conn.execute("SELECT * FROM album_books WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def ensure_album_book(self, name: Any = DEFAULT_ALBUM_NAME) -> dict:
        book_name = str(name or DEFAULT_ALBUM_NAME).strip() or DEFAULT_ALBUM_NAME
        with self._connect() as conn:
            existing = self._album_book_row(conn, book_name)
            if existing:
                return existing
            book_id = f"albm_{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO album_books (id, name, created_at) VALUES (?, ?, ?)",
                (book_id, book_name, iso_now()),
            )
            return {"id": book_id, "name": book_name, "created_at": iso_now()}

    def save_album_photo(
        self,
        *,
        raw: bytes,
        mime: str = "image/jpeg",
        note: str = "",
        mood: str = "",
        book_name: Any = DEFAULT_ALBUM_NAME,
        fingerprint: str = "",
        source_session_tag: str = "",
    ) -> dict:
        if not raw:
            raise ValueError("photo bytes are required.")
        if len(raw) > MAX_PHOTO_BYTES:
            raise ValueError(f"photo is larger than {MAX_PHOTO_BYTES} bytes.")
        book = self.ensure_album_book(book_name)
        photo_id = f"phot_{uuid.uuid4().hex[:12]}"
        digest = str(fingerprint or "").strip() or photo_fingerprint(raw)
        saved_at = iso_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO album_photos
                    (id, book_id, mime, bytes, byte_size, fingerprint, note, mood,
                     source_session_tag, note_ref, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                """,
                (
                    photo_id,
                    book["id"],
                    str(mime or "image/jpeg"),
                    raw,
                    len(raw),
                    digest,
                    str(note or "").strip(),
                    str(mood or "").strip(),
                    str(source_session_tag or "").strip(),
                    saved_at,
                ),
            )
        return {
            "id": photo_id,
            "book_id": book["id"],
            "book_name": book["name"],
            "mime": str(mime or "image/jpeg"),
            "byte_size": len(raw),
            "fingerprint": digest,
            "note": str(note or "").strip(),
            "mood": str(mood or "").strip(),
            "saved_at": saved_at,
        }

    def set_album_photo_note_ref(self, photo_id: str, note_ref: str) -> None:
        """记下这张图的备注在 Supabase 的哪一行，供 Recall 命中后回跳。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE album_photos SET note_ref = ? WHERE id = ?",
                (str(note_ref or "").strip(), str(photo_id)),
            )

    def list_album_books(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT b.id, b.name, b.created_at,
                       COUNT(p.id) AS photo_count,
                       MAX(p.saved_at) AS latest_saved_at
                FROM album_books b
                LEFT JOIN album_photos p ON p.book_id = b.id
                GROUP BY b.id
                ORDER BY b.created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    # 列表查询绝不 SELECT bytes：翻相册只要文字和尺寸，把图一起读出来会让
    # 一次列表请求搬走几十 MB。
    def list_album_photos(self, book_name: Any = "", limit: int = 30) -> list[dict]:
        clamped = max(1, min(int(limit or 30), 200))
        query = """
            SELECT p.id, p.book_id, b.name AS book_name, p.mime, p.byte_size,
                   p.fingerprint, p.note, p.mood, p.source_session_tag,
                   p.note_ref, p.saved_at
            FROM album_photos p
            JOIN album_books b ON b.id = p.book_id
        """
        params: list[Any] = []
        name = str(book_name or "").strip()
        if name:
            query += " WHERE b.name = ?"
            params.append(name)
        query += " ORDER BY p.saved_at DESC LIMIT ?"
        params.append(clamped)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def album_photo_bytes(self, photo_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, mime, bytes, byte_size FROM album_photos WHERE id = ?",
                (str(photo_id),),
            ).fetchone()
        return dict(row) if row else None

    def album_photo_info(self, photo_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT p.id, p.note, p.mood, p.mime, p.byte_size, p.fingerprint,
                          b.name AS book_name FROM album_photos p
                   JOIN album_books b ON b.id = p.book_id WHERE p.id = ?""",
                (str(photo_id),),
            ).fetchone()
        return dict(row) if row else None

    def album_photo_page(self, book_name: str = "", limit: int = 20, cursor: str = "") -> dict:
        """Keyset paging, never OFFSET and never read the image BLOB."""
        name = str(book_name or "").strip()
        limit = max(1, min(int(limit), 100))
        boundary = None
        if cursor:
            try:
                if not isinstance(cursor, str) or len(cursor) > 4096:
                    raise ValueError
                boundary = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
                if (not isinstance(boundary, list) or len(boundary) != 3
                        or not all(isinstance(x, str) for x in boundary) or boundary[0] != name):
                    raise ValueError
            except (ValueError, TypeError, UnicodeError) as exc:
                raise ValueError("这一页的位置无效，请重新翻相册。") from exc
        query = """SELECT p.id, p.note, p.mood, p.saved_at, b.name AS book_name
                   FROM album_photos p JOIN album_books b ON b.id = p.book_id WHERE 1=1"""
        params: list[Any] = []
        if name:
            query += " AND b.name = ?"
            params.append(name)
        if boundary:
            query += " AND (p.saved_at, p.id) < (?, ?)"
            params.extend(boundary[1:])
        query += " ORDER BY p.saved_at DESC, p.id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps(
                [name, last["saved_at"], last["id"]], ensure_ascii=False,
            ).encode()).decode()
        return {"photos": [photo_reference(row) for row in page], "next_cursor": next_cursor}

    def retain_message_media(self, session_tag: str, event_id: str, role: str, media: list[dict]) -> None:
        if role != "user" or not session_tag or not event_id:
            return
        with self._connect() as conn:
            for position, item in enumerate(clean_media(media)):
                conn.execute(
                    "INSERT OR IGNORE INTO album_message_media VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_tag, event_id, role, item["id"], position,
                     json.dumps(item, ensure_ascii=False), iso_now()),
                )

    def record_album_share(self, session_tag: str, event_id: str, share_id: str, photo_id: str) -> dict:
        photo = self.album_photo_info(photo_id)
        if not photo:
            raise ValueError("这张照片不在相册里。")
        if not session_tag or not event_id or not share_id:
            raise ValueError("这次回复没有可用的照片关联。")
        media = {"id": share_id, "name": str(photo["book_name"]), "mime": photo["mime"],
                 **photo_reference(photo)}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT item_id, metadata_json FROM album_message_media
                   WHERE session_tag = ? AND event_id = ? AND role = 'assistant'""",
                (session_tag, event_id),
            ).fetchall()
            for row in rows:
                if row["item_id"] == share_id:
                    existing = json.loads(row["metadata_json"])
                    if existing.get("photo_id") != photo_id:
                        raise ValueError("这次分享的编号已经关联了另一张照片。")
                    return existing
            if len(rows) >= MAX_MEDIA_ITEMS:
                raise ValueError("这次回复已经放了九张照片，先把这些给圆圆看。")
            conn.execute(
                "INSERT INTO album_message_media VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
                (session_tag, event_id, share_id, len(rows), json.dumps(media, ensure_ascii=False), iso_now()),
            )
        return media

    def message_media_batch(self, session_tag: str, events: list[tuple[str, str]]) -> dict[str, list[dict]]:
        keys = list(dict.fromkeys((str(role), str(event_id)) for role, event_id in events
                                  if role in {"user", "assistant"} and event_id))
        found: dict[str, list[dict]] = {}
        with self._connect() as conn:
            for start in range(0, len(keys), 200):
                batch = keys[start:start + 200]
                conditions = " OR ".join("(role = ? AND event_id = ?)" for _ in batch)
                if not conditions:
                    continue
                rows = conn.execute(
                    f"""SELECT role, event_id, metadata_json FROM album_message_media
                        WHERE session_tag = ? AND ({conditions}) ORDER BY position ASC""",
                    [session_tag, *(value for pair in batch for value in pair)],
                ).fetchall()
                for row in rows:
                    found.setdefault(f"{row['role']}:{row['event_id']}", []).append(json.loads(row["metadata_json"]))
        digests = [m["fingerprint"] for items in found.values() for m in items if m.get("fingerprint")]
        saved = self.album_notes_by_fingerprints(digests)
        for items in found.values():
            for media in items:
                photo = saved.get(media.get("fingerprint", ""))
                if photo:
                    media.update(photo_reference(photo))
        return found

    def message_media(self, session_tag: str, event_id: str, role: str) -> list[dict]:
        return self.message_media_batch(session_tag, [(role, event_id)]).get(f"{role}:{event_id}", [])

    # 过期回填的入口：给一批指纹，返回哪些图沈予存过、他当时写了什么。
    # 一次查完，不在 trim 循环里逐张查库。
    def album_notes_by_fingerprints(self, fingerprints: list[str]) -> dict[str, dict]:
        digests = [str(item or "").strip() for item in fingerprints if str(item or "").strip()]
        if not digests:
            return {}
        found: dict[str, dict] = {}
        with self._connect() as conn:
            for start in range(0, len(digests), 200):
                batch = digests[start : start + 200]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"""
                    SELECT p.id, p.fingerprint, p.note, p.mood, b.name AS book_name, p.saved_at
                    FROM album_photos p
                    JOIN album_books b ON b.id = p.book_id
                    WHERE p.fingerprint IN ({placeholders})
                    ORDER BY p.saved_at ASC
                    """,
                    tuple(batch),
                ).fetchall()
                for row in rows:
                    # 同一张图存过多次时留最新那条备注。
                    found[str(row["fingerprint"])] = dict(row)
        return found
