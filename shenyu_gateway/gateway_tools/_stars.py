from __future__ import annotations

from typing import Any, Optional

# Resident contract: tool results stay clean - content, chord, timestamps and
# the ids later calls need. Scores, hit markers and source/embedding internals
# stay on the service layer, where the Admin UI keeps consuming them.
_STAR_PUBLIC_FIELDS = (
    "id",
    "content",
    "chord",
    "chord_sequence",
    "status",
    "is_constant",
    "created_at",
    "updated_at",
)


def _clean_star(star: Any) -> dict[str, Any]:
    if not isinstance(star, dict):
        return {}
    item: dict[str, Any] = {}
    for key in _STAR_PUBLIC_FIELDS:
        value = star.get(key)
        if value is None or value == "" or value == []:
            continue
        item[key] = value
    return item


class StarToolsMixin:
    async def create_star(
        self,
        content: Any,
        chord: str = "",
        chords: Optional[list[str]] = None,
        session_tag: Optional[str] = None,
        status: str = "active",
        is_constant: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        result = await self._stars().create_star(
            content=content,
            chord=chord,
            chords=chords,
            session_tag=session_tag,
            status=status,
            is_constant=is_constant,
            metadata=metadata,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        return {"ok": True, "star_id": result.get("star_id"), "star": _clean_star(result.get("star"))}

    async def list_stars(
        self,
        status: str = "active",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        reviewed: str = "all",
    ) -> dict:
        result = await self._stars().list_stars(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            reviewed=reviewed,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        items = [_clean_star(item) for item in result.get("items") or []]
        return {"ok": True, "count": len(items), "items": items}

    async def search_stars(
        self,
        query: str = "",
        session_tag: Optional[str] = None,
        limit: int = 10,
        log_run: bool = False,
    ) -> dict:
        result = await self._stars().search_stars(
            query=query,
            session_tag=session_tag,
            limit=limit,
            log_run=log_run,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        items = []
        for item in result.get("items") or []:
            cleaned = _clean_star(item)
            if isinstance(item, dict) and item.get("candidate_id"):
                cleaned["candidate_id"] = item["candidate_id"]
            items.append(cleaned)
        out: dict[str, Any] = {"ok": True, "count": len(items), "items": items}
        if result.get("run_id"):
            out["run_id"] = result["run_id"]
        return out

    async def star_review(
        self,
        limit_new: Optional[int] = None,
        candidates_per_star: Optional[int] = None,
        total_candidate_limit: Optional[int] = None,
        session_tag: Optional[str] = None,
    ) -> dict:
        result = await self._stars().review(
            limit_new=limit_new,
            candidates_per_star=candidates_per_star,
            total_candidate_limit=total_candidate_limit,
            session_tag=session_tag,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        items = []
        for entry in result.get("items") or []:
            if not isinstance(entry, dict):
                continue
            candidates = []
            for candidate in entry.get("candidates") or []:
                cleaned = _clean_star(candidate)
                if isinstance(candidate, dict) and candidate.get("candidate_id"):
                    cleaned["candidate_id"] = candidate["candidate_id"]
                candidates.append(cleaned)
            items.append(
                {
                    "star": _clean_star(entry.get("star")),
                    "run_id": entry.get("run_id"),
                    "candidates": candidates,
                }
            )
        out: dict[str, Any] = {"ok": True, "count": len(items), "items": items}
        if result.get("remaining_unreviewed") is not None:
            out["remaining_unreviewed"] = result["remaining_unreviewed"]
        return out

    async def star_feedback(
        self,
        feedback: Any = None,
        run_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        candidate_star_id: Optional[str] = None,
        expected_star_id: Optional[str] = None,
        scored_by: str = "沈予",
        note: str = "",
        metadata: Optional[dict[str, Any]] = None,
        items: Optional[list[dict[str, Any]]] = None,
    ) -> dict:
        result = await self._stars().feedback(
            feedback=feedback,
            run_id=run_id,
            candidate_id=candidate_id,
            candidate_star_id=candidate_star_id,
            expected_star_id=expected_star_id,
            scored_by=scored_by,
            note=note,
            metadata=metadata,
            items=items,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        rows = result.get("feedback")
        if isinstance(rows, dict):
            rows = [rows]
        recorded = [row.get("feedback") for row in rows or [] if isinstance(row, dict) and row.get("feedback")]
        out: dict[str, Any] = {"ok": True, "count": result.get("count", len(recorded))}
        if recorded:
            out["recorded"] = recorded
        return out

    async def connect_constellation(
        self,
        star_ids: Any,
        name: str = "",
        relation_type: str = "constellation",
        scored_by: str = "沈予",
        note: str = "",
    ) -> dict:
        result = await self._stars().connect_constellation(
            star_ids=star_ids,
            name=name,
            relation_type=relation_type,
            scored_by=scored_by,
            note=note,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        out: dict[str, Any] = {
            "ok": True,
            "edge_count": result.get("edge_count"),
            "star_ids": result.get("star_ids"),
        }
        if name:
            out["name"] = name
        return out

    async def mark_constant_star(self, star_id: str, is_constant: bool = True) -> dict:
        result = await self._stars().mark_constant(star_id, is_constant=is_constant)
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        return {"ok": True, "star_id": result.get("star_id") or star_id, "is_constant": is_constant}

    async def archive_star(self, star_id: str) -> dict:
        return await self._stars().archive_star(star_id)

    async def merge_stars(self, source_ids: list, *, content: str = "", chord: str = "", is_constant: bool = False, metadata: dict | None = None) -> dict:
        result = await self._stars().merge_stars(source_ids, content=content, chord=chord, is_constant=is_constant, metadata=metadata)
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        return {
            "ok": True,
            "new_star_id": result.get("new_star_id"),
            "archived_ids": result.get("archived_ids"),
            "new_star": _clean_star(result.get("new_star")),
        }
