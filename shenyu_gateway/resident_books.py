from __future__ import annotations

from typing import Any, Optional

from .conflict_books import ConflictBookService
from .resident_home import home_snapshot
from .runtime import iso_now


BOOKS_TABLE = "shenyu_books"
REVISIONS_TABLE = "shenyu_book_revisions"
ANNOTATIONS_TABLE = "shenyu_book_annotations"
LIVING_SLUGS = {"identity", "home"}


class ResidentBooksService:
    """Unified book facade; legacy conflict storage stays behind the facade."""

    def __init__(self, supabase: Any, *, root=None, runtime_config: Any = None):
        self.supabase = supabase
        self.root = root
        self.runtime_config = runtime_config
        self.conflict_books = ConflictBookService(supabase)

    async def shelf(self) -> dict:
        home = home_snapshot(root=self.root, runtime_config=self.runtime_config) if self.root else home_snapshot(runtime_config=self.runtime_config)
        if not self.supabase:
            return {
                "ok": True,
                "home": home,
                "books": [],
                "warnings": ["Supabase is not configured; living books and origin books are unavailable."],
            }
        books = []
        warnings = []
        try:
            living_rows = await self.supabase.query(
                BOOKS_TABLE,
                params={
                    "select": "id,slug,title,kind,status,revision,updated_at,updated_by,created_at",
                    "kind": "eq.living",
                    "status": "eq.active",
                    "order": "updated_at.desc",
                    "limit": "50",
                },
            )
            books.extend(
                {
                    "kind": "living",
                    "id": row.get("id"),
                    "slug": row.get("slug"),
                    "title": row.get("title"),
                    "status": row.get("status"),
                    "revision": int(row.get("revision") or 0),
                    "updated_at": row.get("updated_at"),
                    "updated_by": row.get("updated_by"),
                }
                for row in living_rows or []
            )
        except Exception as exc:
            warnings.append(f"Living books are unavailable: {self._friendly_error(exc)}")

        origin_result = await self.conflict_books.list_books()
        if origin_result.get("ok"):
            books.extend({"kind": "origin", **book} for book in origin_result.get("books") or [])
        else:
            warnings.append(origin_result.get("error") or "Origin books are unavailable.")
        return {"ok": True, "home": home, "books": books, "warnings": warnings}

    async def read(
        self,
        *,
        book: str = "",
        book_id: str = "",
        title: str = "",
        view: str = "current",
    ) -> dict:
        slug = self._slug(book)
        if slug == "home":
            result = await self._read_living(slug, view=view)
            result["home_snapshot"] = home_snapshot(root=self.root, runtime_config=self.runtime_config) if self.root else home_snapshot(runtime_config=self.runtime_config)
            return result
        if slug in LIVING_SLUGS:
            return await self._read_living(slug, view=view)
        if not self.supabase:
            return self._config_error()
        result = await self.conflict_books.read_book(book_id, title=title)
        if result.get("ok"):
            result["kind"] = "origin"
        return result

    async def write(
        self,
        *,
        book: str,
        content: str,
        mode: str = "replace",
        expected_revision: Optional[int] = None,
        summary: str = "",
        actor: str = "沈予",
    ) -> dict:
        slug = self._slug(book)
        if slug not in LIVING_SLUGS:
            return {"ok": False, "error": "write only supports living books: identity or home", "error_kind": "validation"}
        if not self.supabase:
            return self._config_error()
        body = str(content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required", "error_kind": "validation"}
        try:
            row = await self._ensure_living(slug)
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
        if not row:
            return {"ok": False, "error": "living book is unavailable"}
        current_revision = int(row.get("revision") or 0)
        if expected_revision is not None and int(expected_revision) != current_revision:
            return {
                "ok": False,
                "error": "book changed since it was read; read it again before writing",
                "error_kind": "conflict",
                "current_revision": current_revision,
            }
        mode_key = str(mode or "replace").strip().lower()
        if mode_key not in {"replace", "append"}:
            return {"ok": False, "error": "mode must be replace or append", "error_kind": "validation"}
        next_body = body if mode_key == "replace" or not str(row.get("body") or "").strip() else f"{row.get('body').strip()}\n\n{body}"
        next_revision = current_revision + 1
        stamp = iso_now()
        try:
            revision = await self.supabase.insert(
                REVISIONS_TABLE,
                {
                    "book_id": row["id"],
                    "revision": next_revision,
                    "body": next_body,
                    "summary": str(summary or "").strip(),
                    "actor": str(actor or "沈予").strip() or "沈予",
                    "created_at": stamp,
                },
            )
            updated = await self.supabase.update(
                BOOKS_TABLE,
                {"id": row["id"], "revision": current_revision},
                {
                    "body": next_body,
                    "revision": next_revision,
                    "updated_at": stamp,
                    "updated_by": str(actor or "沈予").strip() or "沈予",
                },
            )
            if not updated:
                return {
                    "ok": False,
                    "error": "book changed before the write was committed; read it again",
                    "error_kind": "conflict",
                    "current_revision": current_revision,
                }
            return {
                "ok": True,
                "book": {**updated[0], "kind": "living"},
                "revision": revision,
            }
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}

    async def annotate(
        self,
        *,
        book: str = "",
        book_id: str = "",
        title: str = "",
        content: str,
        target_revision: Optional[int] = None,
        actor: str = "沈予",
    ) -> dict:
        slug = self._slug(book)
        text = str(content or "").strip()
        if not text:
            return {"ok": False, "error": "content is required", "error_kind": "validation"}
        if slug in LIVING_SLUGS:
            if not self.supabase:
                return self._config_error()
            try:
                row = await self._ensure_living(slug)
            except Exception as exc:
                return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
            if not row:
                return {"ok": False, "error": "living book is unavailable"}
            book_id = str(row["id"])
            target_revision = int(row.get("revision") or 0) if target_revision is None else int(target_revision)
            try:
                annotation = await self.supabase.insert(
                    ANNOTATIONS_TABLE,
                    {
                        "book_id": book_id,
                        "target_revision": target_revision,
                        "content": text,
                        "actor": str(actor or "沈予").strip() or "沈予",
                        "created_at": iso_now(),
                    },
                )
                return {"ok": True, "kind": "living", "annotation": annotation}
            except Exception as exc:
                return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
        if not self.supabase:
            return self._config_error()
        result = await self.conflict_books.annotate_book(book_id, text, title=title)
        if result.get("ok"):
            result["kind"] = "origin"
        return result

    async def _read_living(self, slug: str, *, view: str) -> dict:
        if not self.supabase:
            return self._config_error()
        try:
            row = await self._ensure_living(slug)
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
        if not row:
            return {"ok": False, "error": "living book is unavailable"}
        try:
            annotations = await self.supabase.query(
                ANNOTATIONS_TABLE,
                params={
                    "select": "id,target_revision,content,actor,created_at",
                    "book_id": f"eq.{row['id']}",
                    "order": "created_at.asc",
                    "limit": "500",
                },
            )
            result = {
                "ok": True,
                "kind": "living",
                "book": {**row, "annotations": annotations or []},
            }
            if str(view or "current").strip().lower() in {"history", "all"}:
                result["revisions"] = await self.supabase.query(
                    REVISIONS_TABLE,
                    params={
                        "select": "id,revision,body,summary,actor,created_at",
                        "book_id": f"eq.{row['id']}",
                        "order": "revision.desc",
                        "limit": "100",
                    },
                )
            return result
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}

    async def _ensure_living(self, slug: str) -> Optional[dict]:
        rows = await self.supabase.query(
            BOOKS_TABLE,
            params={
                "select": "id,slug,title,kind,status,body,revision,updated_at,updated_by,created_at",
                "slug": f"eq.{slug}",
                "kind": "eq.living",
                "limit": "1",
            },
        )
        if rows:
            return rows[0]
        titles = {"identity": "我是谁", "home": "家现在"}
        try:
            return await self.supabase.insert(
                BOOKS_TABLE,
                {
                    "slug": slug,
                    "title": titles[slug],
                    "kind": "living",
                    "status": "active",
                    "body": "",
                    "revision": 0,
                },
            )
        except Exception:
            return None

    @staticmethod
    def _slug(value: Any) -> str:
        raw = str(value or "").strip().lower()
        aliases = {
            "我是谁": "identity",
            "自述": "identity",
            "identity": "identity",
            "家现在": "home",
            "home": "home",
            "origin": "origin",
            "来历书": "origin",
            "矛盾书": "origin",
        }
        return aliases.get(raw, raw)

    @staticmethod
    def _config_error() -> dict:
        return {"ok": False, "error": "Supabase is not configured.", "error_kind": "config"}

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        return str(exc)[:1000] or exc.__class__.__name__
