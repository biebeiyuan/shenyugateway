from __future__ import annotations

from typing import Any, Optional


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
        return await self._stars().create_star(
            content=content,
            chord=chord,
            chords=chords,
            session_tag=session_tag,
            status=status,
            is_constant=is_constant,
            metadata=metadata,
        )

    async def list_stars(
        self,
        status: str = "active",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        reviewed: str = "all",
    ) -> dict:
        return await self._stars().list_stars(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            reviewed=reviewed,
        )

    async def search_stars(
        self,
        query: str = "",
        session_tag: Optional[str] = None,
        limit: int = 10,
        log_run: bool = False,
    ) -> dict:
        return await self._stars().search_stars(
            query=query,
            session_tag=session_tag,
            limit=limit,
            log_run=log_run,
        )

    async def star_review(
        self,
        limit_new: Optional[int] = None,
        candidates_per_star: Optional[int] = None,
        total_candidate_limit: Optional[int] = None,
        session_tag: Optional[str] = None,
    ) -> dict:
        return await self._stars().review(
            limit_new=limit_new,
            candidates_per_star=candidates_per_star,
            total_candidate_limit=total_candidate_limit,
            session_tag=session_tag,
        )

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
        return await self._stars().feedback(
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

    async def connect_constellation(
        self,
        star_ids: Any,
        name: str = "",
        relation_type: str = "constellation",
        scored_by: str = "沈予",
        note: str = "",
    ) -> dict:
        return await self._stars().connect_constellation(
            star_ids=star_ids,
            name=name,
            relation_type=relation_type,
            scored_by=scored_by,
            note=note,
        )

    async def mark_constant_star(self, star_id: str, is_constant: bool = True) -> dict:
        return await self._stars().mark_constant(star_id, is_constant=is_constant)

    async def archive_star(self, star_id: str) -> dict:
        return await self._stars().archive_star(star_id)

    async def merge_stars(self, source_ids: list, *, content: str = "", chord: str = "", is_constant: bool = False, metadata: dict | None = None) -> dict:
        return await self._stars().merge_stars(source_ids, content=content, chord=chord, is_constant=is_constant, metadata=metadata)
