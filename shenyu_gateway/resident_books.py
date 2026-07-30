from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .conflict_books import ConflictBookService
from .resident_home import home_overview, home_snapshot
from .runtime import iso_now


BOOKS_TABLE = "shenyu_books"
REVISIONS_TABLE = "shenyu_book_revisions"
ANNOTATIONS_TABLE = "shenyu_book_annotations"
IDENTITY_SLUG = "identity"
HOME_SLUG = "home"


class ResidentBooksService:
    """Three-source resident bookshelf: generated home, living identity, frozen origins."""

    def __init__(self, supabase: Any, *, root=None, runtime_config: Any = None):
        self.supabase = supabase
        self.root = root
        self.runtime_config = runtime_config
        self.conflict_books = ConflictBookService(supabase)

    async def overview(self) -> dict:
        """Return the lightweight bookshelf directory used by context and Admin."""
        home = home_overview()
        identity = None
        origin_books: list[dict] = []
        warnings: list[str] = []
        if not self.supabase:
            return {
                "ok": True,
                "home": home,
                "identity": identity,
                "origin_books": origin_books,
                "warnings": ["Supabase is not configured; identity and origin books are unavailable."],
            }

        try:
            rows = await self.supabase.query(
                BOOKS_TABLE,
                params={
                    "select": "id,slug,title,kind,status,revision,updated_at,updated_by,created_at",
                    "slug": f"eq.{IDENTITY_SLUG}",
                    "status": "eq.active",
                    "limit": "1",
                },
            )
            if rows:
                row = rows[0]
                identity = {
                    "kind": "living",
                    "id": row.get("id"),
                    "slug": IDENTITY_SLUG,
                    "title": row.get("title") or "我是谁",
                    "status": row.get("status") or "active",
                    "revision": int(row.get("revision") or 0),
                    "updated_at": row.get("updated_at"),
                    "updated_by": row.get("updated_by"),
                }
        except Exception as exc:
            warnings.append(f"Identity book is unavailable: {self._friendly_error(exc)}")

        origin_result = await self.conflict_books.list_books()
        if origin_result.get("ok"):
            origin_books = origin_result.get("books") or []
        else:
            warnings.append(origin_result.get("error") or "Origin books are unavailable.")
        return {
            "ok": True,
            "home": home,
            "identity": identity,
            "origin_books": origin_books,
            "warnings": warnings,
        }

    async def list_books(self) -> dict:
        """Return a tool-facing shelf directory without any book bodies."""
        overview = await self.overview()
        home = overview.get("home") or {}
        home_entry = {
            "book": HOME_SLUG,
            "title": "家现在",
            "kind": "snapshot",
        }
        for key in ("current_week", "current_week_changes", "last_confirmed_at"):
            if home.get(key) is not None:
                home_entry[key] = home[key]

        identity = overview.get("identity") or None
        identity_entry = None
        if identity:
            identity_entry = {
                "book": IDENTITY_SLUG,
                "title": identity.get("title") or "我是谁",
                "kind": "living",
                "revision": int(identity.get("revision") or 0),
                "status": identity.get("status") or "active",
                "updated_at": identity.get("updated_at"),
                "updated_by": identity.get("updated_by"),
            }

        origin_books = []
        for item in overview.get("origin_books") or []:
            origin_books.append(
                {
                    "book": "origin",
                    "book_id": item.get("id"),
                    "title": item.get("title") or "",
                    "kind": "origin",
                    "status": item.get("status") or "open",
                    "read_count": int(item.get("read_count") or 0),
                    "last_read_at": item.get("last_read_at"),
                    "created_at": item.get("created_at"),
                }
            )

        result = {
            "ok": True,
            "count": 1 + (1 if identity_entry else 0) + len(origin_books),
            "home": home_entry,
            "identity": identity_entry,
            "origin_books": origin_books,
        }
        if overview.get("warnings"):
            result["warnings"] = overview["warnings"]
        return result

    async def read(
        self,
        *,
        book: str = "",
        book_id: str = "",
        title: str = "",
        view: str = "current",
    ) -> dict:
        slug = self._slug(book)
        if slug == HOME_SLUG:
            return await self._read_home()
        if slug == IDENTITY_SLUG:
            return await self._read_identity(view=view)
        if not self.supabase:
            return self._config_error()
        if slug == "origin" and not str(book_id or "").strip() and not str(title or "").strip():
            return {
                "ok": False,
                "error": "origin 是多本来历书；先用 action=list 看书架，再用 book_id 或精确 title 读取。",
                "error_kind": "validation",
            }
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
        if slug == HOME_SLUG:
            return {
                "ok": False,
                "error": "家现在由系统自动生成，不能手写替换；可以追加批注。",
                "error_kind": "read_only",
            }
        if slug != IDENTITY_SLUG:
            return {"ok": False, "error": "write only supports 我是谁", "error_kind": "validation"}
        if not self.supabase:
            return self._config_error()
        body = str(content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required", "error_kind": "validation"}
        try:
            row = await self._ensure_identity()
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
        if not row:
            return {"ok": False, "error": "identity book is unavailable"}
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
            return {"ok": True, "book": {**updated[0], "kind": "living"}, "revision": revision}
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
        if slug in {IDENTITY_SLUG, HOME_SLUG}:
            if not self.supabase:
                return self._config_error()
            try:
                row = await (self._ensure_identity() if slug == IDENTITY_SLUG else self._ensure_home_anchor())
            except Exception as exc:
                return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
            if not row:
                return {"ok": False, "error": "book annotation anchor is unavailable"}
            revision = int(row.get("revision") or 0) if slug == IDENTITY_SLUG else 0
            if slug == IDENTITY_SLUG and target_revision is not None:
                revision = int(target_revision)
            try:
                annotation = await self.supabase.insert(
                    ANNOTATIONS_TABLE,
                    {
                        "book_id": str(row["id"]),
                        "target_revision": revision,
                        "content": text,
                        "actor": str(actor or "沈予").strip() or "沈予",
                        "created_at": iso_now(),
                    },
                )
                return {"ok": True, "kind": "living" if slug == IDENTITY_SLUG else "snapshot", "annotation": annotation}
            except Exception as exc:
                return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
        if not self.supabase:
            return self._config_error()
        result = await self.conflict_books.annotate_book(book_id, text, title=title)
        if result.get("ok"):
            result["kind"] = "origin"
        return result

    async def _read_home(self) -> dict:
        snapshot = home_snapshot(root=self.root, runtime_config=self.runtime_config) if self.root else home_snapshot(runtime_config=self.runtime_config)
        annotations: list[dict] = []
        anchor = None
        warnings: list[str] = []
        if self.supabase:
            try:
                anchor = await self._ensure_home_anchor()
                if anchor:
                    annotations = await self._annotations(str(anchor["id"]))
            except Exception as exc:
                warnings.append(f"Home annotations are unavailable: {self._friendly_error(exc)}")
        else:
            warnings.append("Supabase is not configured; home annotations are unavailable.")
        return {
            "ok": True,
            "kind": "snapshot",
            "book": {
                "id": (anchor or {}).get("id"),
                "slug": HOME_SLUG,
                "title": "家现在",
                "kind": "snapshot",
                "annotations": annotations,
            },
            "snapshot": snapshot,
            "warnings": warnings,
        }

    async def _read_identity(self, *, view: str) -> dict:
        if not self.supabase:
            return self._config_error()
        try:
            row = await self._ensure_identity()
        except Exception as exc:
            return {"ok": False, "error": self._friendly_error(exc), "error_kind": "exception"}
        if not row:
            return {"ok": False, "error": "identity book is unavailable"}
        try:
            result = {
                "ok": True,
                "kind": "living",
                "book": {**row, "kind": "living", "annotations": await self._annotations(str(row["id"]))},
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

    async def _annotations(self, book_id: str) -> list[dict]:
        return await self.supabase.query(
            ANNOTATIONS_TABLE,
            params={
                "select": "id,target_revision,content,actor,created_at",
                "book_id": f"eq.{book_id}",
                "order": "created_at.asc",
                "limit": "500",
            },
        ) or []

    async def _ensure_identity(self) -> Optional[dict]:
        rows = await self.supabase.query(
            BOOKS_TABLE,
            params={
                "select": "id,slug,title,kind,status,body,revision,updated_at,updated_by,created_at",
                "slug": f"eq.{IDENTITY_SLUG}",
                "limit": "1",
            },
        )
        if rows:
            return rows[0]
        try:
            return await self.supabase.insert(
                BOOKS_TABLE,
                {"slug": IDENTITY_SLUG, "title": "我是谁", "kind": "living", "status": "active", "body": "", "revision": 0},
            )
        except Exception:
            return None

    async def _ensure_home_anchor(self) -> Optional[dict]:
        rows = await self.supabase.query(
            BOOKS_TABLE,
            params={
                "select": "id,slug,title,kind,status,revision,updated_at,created_at",
                "slug": f"eq.{HOME_SLUG}",
                "limit": "1",
            },
        )
        if rows:
            return rows[0]
        try:
            return await self.supabase.insert(
                BOOKS_TABLE,
                {"slug": HOME_SLUG, "title": "家现在", "kind": "snapshot", "status": "active", "body": "", "revision": 0},
            )
        except Exception:
            return None

    @staticmethod
    def _slug(value: Any) -> str:
        raw = str(value or "").strip().lower()
        aliases = {
            "我是谁": IDENTITY_SLUG,
            "自述": IDENTITY_SLUG,
            "identity": IDENTITY_SLUG,
            "家现在": HOME_SLUG,
            "home": HOME_SLUG,
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


def render_bookshelf_overview(overview: dict) -> str:
    if not overview:
        return ""
    lines = ["## 书架一览"]
    home = overview.get("home") or {}
    changes = int(home.get("current_week_changes") or 0)
    confirmed = _short_date(home.get("last_confirmed_at"))
    home_detail = f"本周 {changes} 条变化"
    if confirmed:
        home_detail += f"，最后确认于 {confirmed}"
    lines.append(f"- 家现在：{home_detail}")

    identity = overview.get("identity") or {}
    if identity:
        identity_detail = f"第 {int(identity.get('revision') or 0)} 版"
        actor = str(identity.get("updated_by") or "").strip()
        updated = _short_date(identity.get("updated_at"))
        if actor:
            identity_detail += f"，最后由{actor}修改"
        if updated:
            identity_detail += f"于 {updated}"
        lines.append(f"- 我是谁：{identity_detail}")
    else:
        lines.append("- 我是谁：还没有写下第一版")

    origins = overview.get("origin_books") or []
    titles = [f"《{str(book.get('title') or '').strip()}》" for book in origins if str(book.get("title") or "").strip()]
    origin_detail = f"{len(origins)} 本"
    if titles:
        origin_detail += "——" + "、".join(titles)
    lines.append(f"- 来历书：{origin_detail}")
    return "\n".join(lines)


def _short_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return f"{parsed.month}.{parsed.day}"
    except (TypeError, ValueError):
        parts = raw[:10].split("-")
        if len(parts) == 3:
            try:
                return f"{int(parts[1])}.{int(parts[2])}"
            except ValueError:
                pass
        return raw[:10]
