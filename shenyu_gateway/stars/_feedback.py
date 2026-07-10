from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from ..runtime import iso_now, logger
from ._helpers import (
    _feedback_value, _json_dict, _node_id,
    STAR_CANDIDATE_TABLE, STAR_FEEDBACK_TABLE, STAR_TABLE,
    FEEDBACK_VALUES, POSITIVE_FEEDBACK, NEGATIVE_FEEDBACK,
)


def _first_nonempty(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


class FeedbackMixin:

    async def feedback(
        self,
        *,
        feedback: Any = None,
        run_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        candidate_star_id: Optional[str] = None,
        expected_star_id: Optional[str] = None,
        scored_by: str = "沈予",
        note: str = "",
        metadata: Optional[dict[str, Any]] = None,
        items: Any = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        payloads, error = self._feedback_payloads(
            feedback=feedback,
            items=items,
            run_id=run_id,
            candidate_id=candidate_id,
            candidate_star_id=candidate_star_id,
            expected_star_id=expected_star_id,
            scored_by=scored_by,
            note=note,
            metadata=metadata,
        )
        if error:
            return {"ok": False, "error": error}

        rows = []
        for payload in payloads:
            rows.append(await self._feedback_one(payload))

        return {
            "ok": True,
            "count": len(rows),
            "feedback": rows[0] if len(rows) == 1 else rows,
        }

    def _feedback_payloads(
        self,
        *,
        feedback: Any,
        items: Any,
        run_id: Optional[str],
        candidate_id: Optional[str],
        candidate_star_id: Optional[str],
        expected_star_id: Optional[str],
        scored_by: str,
        note: str,
        metadata: Optional[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        default_feedback = _feedback_value(feedback) if isinstance(feedback, str) else ""
        default_scored_by = (scored_by or "沈予").strip() or "沈予"
        default_note = (note or "").strip()
        default_metadata = _json_dict(metadata)
        default_run_id = _node_id(run_id)
        default_candidate_id = _node_id(candidate_id)
        default_candidate_node_id = _node_id(candidate_star_id)
        default_expected_node_id = _node_id(expected_star_id)
        default_expected_node_type = "star" if default_expected_node_id else None

        if isinstance(items, dict):
            raw_items: list[Any] = [items]
        elif isinstance(items, (list, tuple)):
            raw_items = list(items)
        elif items is not None:
            return [], "items must be an object or an array of feedback objects."
        elif isinstance(feedback, list):
            raw_items = list(feedback)
        elif isinstance(feedback, dict):
            raw_items = [feedback]
        else:
            raw_items = [None]

        payloads: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_items):
            if raw is None:
                raw_dict: dict[str, Any] = {}
            elif isinstance(raw, dict):
                raw_dict = raw
            else:
                return [], f"feedback[{index}] must be an object."

            feedback_key = _feedback_value(
                _first_nonempty(raw_dict, "feedback", "label", "action", "value") or default_feedback
            )
            if feedback_key not in FEEDBACK_VALUES:
                return [], f"feedback[{index}] must be one of {sorted(FEEDBACK_VALUES)}."

            item_metadata = _json_dict(default_metadata)
            item_metadata.update(_json_dict(raw_dict.get("metadata")))
            item_run_id = _node_id(raw_dict.get("run_id")) or default_run_id or None
            item_candidate_id = _node_id(raw_dict.get("candidate_id")) or default_candidate_id or None
            item_candidate_node_id = (
                _node_id(_first_nonempty(raw_dict, "candidate_star_id", "candidate_node_id", "star_id"))
                or default_candidate_node_id
                or None
            )
            item_candidate_node_type = _node_id(raw_dict.get("candidate_node_type")) or None
            if not item_candidate_node_type and item_candidate_node_id:
                item_candidate_node_type = "star"

            item_expected_node_id = (
                _node_id(raw_dict.get("expected_star_id"))
                or _node_id(raw_dict.get("expected_node_id"))
                or default_expected_node_id
                or None
            )
            item_expected_node_type = _node_id(raw_dict.get("expected_node_type")) or default_expected_node_type
            if not item_expected_node_type and item_expected_node_id:
                item_expected_node_type = "star"

            payloads.append(
                {
                    "run_id": item_run_id,
                    "candidate_id": item_candidate_id,
                    "candidate_node_type": item_candidate_node_type,
                    "candidate_node_id": item_candidate_node_id,
                    "expected_node_type": item_expected_node_type,
                    "expected_node_id": item_expected_node_id,
                    "feedback": feedback_key,
                    "scored_by": str(raw_dict.get("scored_by") or default_scored_by).strip() or "沈予",
                    "note": str(
                        _first_nonempty(raw_dict, "note", "reason", "comment") or default_note
                    ).strip(),
                    "metadata": item_metadata,
                }
            )

        if not payloads:
            return [], "feedback payload is required."
        return payloads, None

    async def _feedback_one(self, payload: dict[str, Any]) -> dict[str, Any]:
        feedback_key = str(payload.get("feedback") or "").strip().lower()
        candidate_id = _node_id(payload.get("candidate_id"))
        candidate_row = await self._get_candidate(candidate_id) if candidate_id else None
        candidate_node_id = _node_id(payload.get("candidate_node_id")) or _node_id((candidate_row or {}).get("candidate_node_id"))
        candidate_node_type = _node_id(payload.get("candidate_node_type")) or _node_id((candidate_row or {}).get("candidate_node_type"))
        if not candidate_node_type and candidate_node_id:
            candidate_node_type = "star"
        run_id = _node_id(payload.get("run_id")) or _node_id((candidate_row or {}).get("run_id"))
        if not candidate_row and candidate_node_id:
            candidate_row = await self._get_candidate_by_node_id(candidate_node_id, run_id=run_id)
            if candidate_row:
                candidate_id = candidate_id or _node_id(candidate_row.get("id"))
                candidate_node_type = candidate_node_type or _node_id(candidate_row.get("candidate_node_type")) or "star"
        expected_node_id = _node_id(payload.get("expected_node_id"))
        expected_node_type = _node_id(payload.get("expected_node_type")) or ("star" if expected_node_id else None)
        metadata_dict = _json_dict(payload.get("metadata"))
        row = await self.supabase.insert(
            STAR_FEEDBACK_TABLE,
            {
                "run_id": run_id or None,
                "candidate_id": candidate_id or None,
                "candidate_node_type": candidate_node_type or None,
                "candidate_node_id": candidate_node_id or None,
                "expected_node_type": expected_node_type or None,
                "expected_node_id": expected_node_id or None,
                "feedback": feedback_key,
                "scored_by": (payload.get("scored_by") or "沈予").strip() or "沈予",
                "note": (payload.get("note") or "").strip(),
                "metadata": metadata_dict,
            },
        )
        if candidate_id:
            try:
                await self.supabase.update(STAR_CANDIDATE_TABLE, {"id": candidate_id}, {"action_status": feedback_key})
            except Exception as exc:
                logger.warning("[Star] Failed to update candidate feedback: id=%s error=%s", candidate_id, exc)
        if self._is_admin_feedback((payload.get("scored_by") or "沈予").strip() or "沈予", metadata_dict):
            try:
                await self._maybe_mark_admin_reviewed(
                    run_id=run_id or None,
                    scored_by=(payload.get("scored_by") or "沈予").strip() or "沈予",
                    feedback=feedback_key,
                )
            except Exception as exc:
                logger.warning("[Star] Failed to mark admin review state: run_id=%s error=%s", run_id, exc)
        return row

    async def _get_candidate(self, candidate_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not candidate_id:
            return None
        rows = await self.supabase.query(
            STAR_CANDIDATE_TABLE,
            {"select": "*", "id": f"eq.{candidate_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    async def _get_candidate_by_node_id(self, candidate_node_id: Optional[str], *, run_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        candidate_node_id = _node_id(candidate_node_id)
        if not candidate_node_id:
            return None
        params: dict[str, str] = {
            "select": "*",
            "candidate_node_id": f"eq.{candidate_node_id}",
            "order": "created_at.desc",
            "limit": "1",
        }
        if run_id:
            params["run_id"] = f"eq.{run_id}"
        rows = await self.supabase.query(STAR_CANDIDATE_TABLE, params)
        return rows[0] if rows else None
