from __future__ import annotations

import random
from typing import Optional

from shenyu_gateway.runtime import now as _now, parse_ts as _parse_ts
from shenyu_gateway.utils import shorten as _shorten

from ._helpers import _clamp, _keyword_overlap_score, _split_paragraph_chunks


class CompatToolsMixin:
    async def surface_passages(self, query: str, session_tag: Optional[str], limit: int = 3) -> dict:
        candidates = await self._collect_primary_text_candidates(
            session_tag=session_tag,
            categories={"room", "message_board"},
        )
        scored = []
        for item in candidates:
            score = self._score_passage(query, item)
            if score <= 0:
                continue
            probability = _clamp(score * item.get("novelty_modifier", 1.0), 0.15, 0.95)
            rolled = random.random() <= probability
            if not rolled:
                continue
            scored.append(
                {
                    **item,
                    "score": round(score, 3),
                    "probability": round(probability, 3),
                    "why": self._why_passage(query, item, score),
                }
            )

        scored.sort(key=lambda row: row["score"], reverse=True)
        passages = scored[: max(1, min(limit, 8))]
        return {"ok": True, "query": query, "count": len(passages), "passages": passages}

    async def _collect_primary_text_candidates(self, session_tag: Optional[str], categories: Optional[set[str]] = None) -> list[dict]:
        if not self.supabase:
            return []

        selected = categories or {"diary", "letter", "paper", "room", "message_board"}
        journal_categories = selected & {"diary", "letter", "paper", "lock", "annotation", "life_tick"}
        items: list[dict] = []

        if journal_categories:
            journal_rows = await self._safe_query(
                "journal",
                {"order": "created_at.desc", "limit": "32", "select": "id,title,content,created_at,category,mood,session_tag"},
            )
            for row in journal_rows:
                category = row.get("category") or "diary"
                if category not in journal_categories:
                    continue
                source_kind = f"journal:{category}"
                items.extend(
                    self._row_to_chunks(
                        source_kind,
                        row,
                        row.get("title"),
                        row.get("content"),
                        row.get("created_at"),
                        category=category,
                    )
                )

        if "room" in selected:
            room_params = {"order": "updated_at.desc", "limit": "8", "select": "id,title,content,updated_at,status,visibility,session_tag"}
            if session_tag:
                room_params["or"] = f"(session_tag.eq.{session_tag},visibility.eq.open,visibility.eq.self)"
            room_rows = await self._safe_query("room", room_params)
            for row in room_rows:
                items.extend(self._row_to_chunks("room", row, row.get("title"), row.get("content"), row.get("updated_at"), category="room"))

        if "message_board" in selected:
            board_rows = await self._safe_query(
                "message_board",
                {"order": "created_at.desc", "limit": "10", "select": "id,sender,content,created_at"},
            )
            for row in board_rows:
                items.append(
                    {
                        "source_table": "message_board",
                        "source_id": row.get("id"),
                        "title": f"Message from {row.get('sender', 'unknown')}",
                        "excerpt": _shorten(row.get("content") or "", 260),
                        "full_text": row.get("content") or "",
                        "created_at": row.get("created_at"),
                        "chunk_index": 0,
                        "content_kind": "message",
                        "base_salience": 0.55,
                        "novelty_modifier": 1.0,
                    }
                )

        return items

    def _row_to_chunks(
        self,
        source_table: str,
        row: dict,
        title: Optional[str],
        content: Optional[str],
        created_at: Optional[str],
        category: Optional[str] = None,
    ) -> list[dict]:
        chunks = _split_paragraph_chunks(content or "")
        if not chunks and content:
            chunks = [content]

        items = []
        for idx, chunk in enumerate(chunks):
            base = self._base_salience_for_source(source_table, category)
            if idx == 0:
                base += 0.04
            items.append(
                {
                    "source_table": source_table.split(":")[0],
                    "source_id": row.get("id"),
                    "title": title or "untitled",
                    "excerpt": _shorten(chunk, 260),
                    "full_text": chunk,
                    "created_at": created_at,
                    "chunk_index": idx,
                    "content_kind": category or source_table,
                    "base_salience": base,
                    "novelty_modifier": 1.0,
                }
            )
        return items

    def _score_passage(self, query: str, item: dict) -> float:
        keyword_score = _keyword_overlap_score(query, item.get("title", "") + "\n" + item.get("full_text", ""))
        recency_score = self._recency_score(item.get("created_at"))
        length_bonus = 0.08 if 80 <= len(item.get("full_text", "")) <= 340 else 0.0
        body_bonus = self._body_bonus_for_item(item)
        return _clamp(item.get("base_salience", 0.5) * 0.45 + keyword_score * 0.35 + recency_score * 0.12 + body_bonus + length_bonus, 0.0, 1.0)

    def _why_passage(self, query: str, item: dict, score: float) -> list[str]:
        reasons = []
        if _keyword_overlap_score(query, item.get("title", "") + "\n" + item.get("full_text", "")) >= 0.4:
            reasons.append("theme overlap")
        content_kind = item.get("content_kind")
        if content_kind in {"room", "diary"}:
            reasons.append("core primary text")
        elif item.get("source_table") == "message_board":
            reasons.append("conversation-adjacent text")
        elif content_kind in {"letter", "paper"}:
            reasons.append("secondary primary text")
        if self._recency_score(item.get("created_at")) >= 0.6:
            reasons.append("recent enough to feel alive")
        if score >= 0.75:
            reasons.append("strong surfaced match")
        return reasons or ["soft surfaced match"]

    def _base_salience_for_source(self, source_table: str, category: Optional[str]) -> float:
        if category == "room":
            return 0.83
        if category == "diary":
            return 0.82
        if category == "letter":
            return 0.72
        if category == "paper":
            return 0.72
        if source_table == "room":
            return 0.83
        if source_table == "message_board":
            return 0.76
        return 0.64

    def _body_bonus_for_item(self, item: dict) -> float:
        content_kind = item.get("content_kind")
        if content_kind in {"room", "diary"}:
            return 0.13
        if item.get("source_table") == "message_board":
            return 0.11
        if content_kind == "letter":
            return 0.08
        if content_kind == "paper":
            return 0.08
        return 0.05

    def _recency_score(self, created_at: Optional[str]) -> float:
        dt = _parse_ts(created_at)
        if not dt:
            return 0.2
        days = max((_now() - dt).days, 0)
        if days <= 1:
            return 1.0
        if days <= 3:
            return 0.8
        if days <= 7:
            return 0.65
        if days <= 14:
            return 0.45
        return 0.25
