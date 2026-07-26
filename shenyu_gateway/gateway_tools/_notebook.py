from __future__ import annotations

import re
from typing import Any, Optional

from shenyu_gateway.runtime import iso_now as _iso_now


class NotebookToolsMixin:
    def _notebook_scope(self, scope: Optional[str]) -> str:
        raw = str(scope or "shared").strip().lower()
        if raw in {"hisense", "海信"}:
            return "hisense"
        if raw in {"handoff", "交接"}:
            return "handoff"
        return "shared"

    def _notebook_tags(self, tags: Optional[Any], scope: Optional[str]) -> list[str]:
        result: list[str] = []

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)

        if isinstance(tags, str):
            for item in re.split(r"[,，\s]+", tags):
                add(item)
        elif isinstance(tags, list):
            for item in tags:
                add(item)
        elif tags:
            add(tags)

        scope_key = self._notebook_scope(scope)
        if scope_key == "hisense":
            add("hisense")
        elif scope_key == "handoff":
            add("handoff")
            add("hisense")
        return result

    def _notebook_filter_tag(self, tag: Optional[Any], scope: Optional[str]) -> str:
        explicit = str(tag or "").strip()
        if explicit:
            return explicit.replace("{", "").replace("}", "").replace(",", "")
        scope_key = self._notebook_scope(scope)
        if scope_key == "hisense":
            return "hisense"
        if scope_key == "handoff":
            return "handoff"
        return ""

    def _notebook_metadata(self, metadata: Optional[dict], scope: Optional[str]) -> dict:
        data = dict(metadata) if isinstance(metadata, dict) else {}
        scope_key = self._notebook_scope(scope)
        if scope_key != "shared":
            data.setdefault("scope", scope_key)
        return data

    async def notebook_list(self, type_filter: Optional[str], status: str, limit: int, tag: Optional[str] = None, scope: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase not configured"}
        limit = max(1, min(int(limit or 10), 20))
        status_key = (status or "active").strip().lower()
        params: dict[str, str] = {
            "order": "pinned.desc,updated_at.desc",
            "limit": str(limit),
            "select": "id,type,content,tags,status,pinned,created_at,updated_at",
        }
        if status_key and status_key != "all":
            params["status"] = f"eq.{status_key}"
        if type_filter:
            params["type"] = f"eq.{type_filter}"
        filter_tag = self._notebook_filter_tag(tag, scope)
        if filter_tag:
            params["tags"] = f"cs.{{{filter_tag}}}"
        try:
            rows = await self.supabase.query("shenyu_notebook", params)
            return {"ok": True, "count": len(rows or []), "data": rows or []}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def notebook_write(self, type_: Optional[str], content: str, tags: Optional[list], metadata: Optional[dict], session_tag: Optional[str], scope: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase not configured"}
        body = (content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required"}
        scope_key = self._notebook_scope(scope)
        note_type = (type_ or "").strip() or ("handoff" if scope_key == "handoff" else "note")
        data: dict[str, Any] = {"type": note_type, "content": body, "status": "active"}
        normalized_tags = self._notebook_tags(tags, scope_key)
        if normalized_tags:
            data["tags"] = normalized_tags
        normalized_metadata = self._notebook_metadata(metadata, scope_key)
        if normalized_metadata:
            data["metadata"] = normalized_metadata
        if session_tag:
            data["session_tag"] = session_tag
        try:
            result = await self.supabase.insert("shenyu_notebook", data)
            return {"ok": True, "data": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def notebook_update(self, id_: str, content: Optional[str], status: Optional[str], tags: Optional[list], type_: Optional[str], pinned: Optional[bool], metadata: Optional[dict]) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase not configured"}
        if not id_:
            return {"ok": False, "error": "id is required"}
        update_data: dict[str, Any] = {}
        if content is not None:
            update_data["content"] = content
        if status is not None:
            update_data["status"] = status
        if tags is not None:
            update_data["tags"] = tags
        if type_ is not None:
            update_data["type"] = type_
        if pinned is not None:
            update_data["pinned"] = pinned
        if metadata is not None:
            update_data["metadata"] = metadata
        if not update_data:
            return {"ok": False, "error": "Nothing to update"}
        update_data["updated_at"] = _iso_now()
        try:
            result = await self.supabase.update("shenyu_notebook", match={"id": id_}, data=update_data)
            return {"ok": True, "data": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
