from __future__ import annotations

from typing import Optional


class BooksToolsMixin:
    async def books(
        self,
        *,
        action: str = "",
        book: str = "",
        book_id: str = "",
        title: str = "",
        content: str = "",
        mode: str = "replace",
        expected_revision: Optional[int] = None,
        target_revision: Optional[int] = None,
        summary: str = "",
        view: str = "current",
        actor: str = "沈予",
    ) -> dict:
        service = self._resident_books()
        action_key = str(action or "").strip().lower()
        if action_key == "read":
            return await service.read(book=book, book_id=book_id, title=title, view=view)
        if action_key == "write":
            return await service.write(
                book=book,
                content=content,
                mode=mode,
                expected_revision=expected_revision,
                summary=summary,
                actor=actor,
            )
        if action_key == "annotate":
            return await service.annotate(
                book=book,
                book_id=book_id,
                title=title,
                content=content,
                target_revision=target_revision,
                actor=actor,
            )
        return {"ok": False, "error": "action must be read, write, or annotate", "error_kind": "validation"}

    async def conflict_list(self) -> dict:
        return await self._conflict_books().list_books()

    async def conflict_read(self, book_id: str = "", title: str = "") -> dict:
        return await self._conflict_books().read_book(book_id, title=title)

    async def conflict_annotate(self, book_id: str = "", content: str = "", title: str = "") -> dict:
        return await self._conflict_books().annotate_book(book_id, content, title=title)
