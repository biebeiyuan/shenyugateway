from __future__ import annotations

import re
from typing import Any, Optional

from .runtime import iso_now


class AtomicMemoryService:
    def __init__(self, cfg: Any, supabase_client: Any):
        self.cfg = cfg
        self.supabase_client = supabase_client

    async def process_inline_memories(
        self,
        session: dict,
        inline_memories: list[Any],
        assistant_text: str,
        source_model: str,
    ) -> dict[str, Any]:
        if not self.cfg.enable_inline_memory_capture:
            return {"ok": False, "reason": "inline memory capture disabled."}
        if not self.supabase_client:
            return {"ok": False, "reason": "Supabase is not configured."}

        notes = [item for item in inline_memories if self._inline_note_content(item)]
        if not notes:
            return {"ok": False, "reason": "no inline memories."}

        inserted: list[str | None] = []
        discarded = 0
        for note in notes[:4]:
            memory = self._inline_note_to_active_memory(note, session, source_model)
            if not memory:
                discarded += 1
                continue
            row = await self.supabase_client.insert("atomic_memories", memory)
            inserted.append(row.get("id") if isinstance(row, dict) else None)

        return {
            "ok": True,
            "inline_count": len(notes),
            "inserted_count": len([item for item in inserted if item]),
            "discarded_count": discarded,
        }

    def _inline_note_content(self, note: Any) -> str:
        if isinstance(note, dict):
            content = str(note.get("content") or "").strip()
        else:
            content = str(note or "").strip()
        if not content:
            return ""
        if not re.sub(r"[\W_]+", "", content, flags=re.UNICODE):
            return ""
        return content

    def _inline_note_attrs(self, note: Any) -> dict[str, str]:
        if isinstance(note, dict) and isinstance(note.get("attrs"), dict):
            return {
                str(key).lower(): str(value).strip()
                for key, value in note["attrs"].items()
                if str(value).strip()
            }
        return {}

    def _split_attr_list(self, raw: str) -> list[str]:
        if not raw:
            return []
        return [item.strip() for item in re.split(r"[,，、\s]+", raw) if item.strip()][:16]

    def _int_attr(self, attrs: dict[str, str], name: str, fallback: int, min_value: int, max_value: int) -> int:
        try:
            value = int(attrs.get(name) or fallback)
        except (TypeError, ValueError):
            value = fallback
        return max(min_value, min(value, max_value))

    def _inline_note_to_active_memory(self, note: Any, session: dict, source_model: str) -> Optional[dict]:
        content = self._inline_note_content(note)
        if not content:
            return None
        attrs = self._inline_note_attrs(note)
        now = iso_now()
        subject = self._choice(attrs.get("subject") or attrs.get("owner"), {"圆圆", "沈予", "我们"}, "沈予")
        owner = self._subject_scope(subject)
        return {
            "session_tag": session.get("session_tag") or "default",
            "subject": subject,
            "owner": owner,
            "applies_to": owner,
            "speaker_perspective": owner,
            "content_surface": content,
            "quote": attrs.get("quote", ""),
            "time_hint": attrs.get("time") or attrs.get("time_hint", ""),
            "memory_type": self._memory_type(attrs.get("memory_type") or attrs.get("type") or attrs.get("kind")),
            "tier": self._int_attr(attrs, "tier", 2, 1, 4),
            "importance": self._int_attr(attrs, "importance", 3, 1, 5),
            "heat": 0.68,
            "entities_json": self._split_attr_list(attrs.get("entities", "")),
            "tags_json": self._split_attr_list(attrs.get("tags", "")),
            "source_session_id": session.get("id"),
            "source_message_ids_json": [],
            "source_excerpt": attrs.get("source_excerpt", ""),
            "source_model": f"inline-mem:{source_model}",
            "status": "active",
            "activation_count": 0,
            "created_at": now,
            "updated_at": now,
        }

    def _choice(self, value: Any, allowed: set[str], fallback: str) -> str:
        raw = str(value or "").strip()
        return raw if raw in allowed else fallback

    def _subject_scope(self, subject: str) -> str:
        return {
            "圆圆": "user",
            "沈予": "assistant",
            "我们": "shared",
        }.get(subject, "assistant")

    def _memory_type(self, value: Any) -> str:
        raw = str(value or "").strip()
        aliases = {
            "state": "emotion",
            "event": "fact",
            "project": "fact",
            "health": "fact",
            "routine": "fact",
            "identity": "fact",
            "other": "fact",
        }
        raw = aliases.get(raw, raw)
        return self._choice(
            raw,
            {"emotion", "commitment", "fact", "relation", "preference", "boundary"},
            "fact",
        )
