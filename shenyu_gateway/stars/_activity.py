from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from ..request_logs import _mark_request_log_phase
from ..runtime import logger, now as _now, parse_ts as _parse_ts
from ._helpers import (
    STAR_ACTIVATION_TABLE, STAR_CANDIDATE_TABLE, STAR_FEEDBACK_TABLE, STAR_LINK_TABLE,
    NEGATIVE_FEEDBACK, POSITIVE_FEEDBACK,
    _clamp, _node_id, _safe_float, _safe_int,
)


class ActivityMixin:

    async def _harmony_scores(self, anchor_ids: list[str], *, trace_log: Optional[dict] = None) -> dict[str, float]:
        anchor_ids = [item for item in anchor_ids if item]
        if not anchor_ids:
            return {}
        id_filter = "in.(" + ",".join(anchor_ids) + ")"
        rows: list[dict[str, Any]] = []
        try:
            _mark_request_log_phase(trace_log, "stars.harmony_from_query_start", detail={"anchors": len(anchor_ids)})
            from_rows = await self.supabase.query(
                STAR_LINK_TABLE,
                {
                    "select": "from_node_id,to_node_id,relation_type,confidence,weight,bidirectional,status",
                    "from_node_type": "eq.star",
                    "to_node_type": "eq.star",
                    "from_node_id": id_filter,
                    "status": "eq.active",
                    "limit": "500",
                },
            )
            rows.extend(from_rows)
            _mark_request_log_phase(trace_log, "stars.harmony_from_query_done", detail={"rows": len(from_rows)})
        except Exception:
            _mark_request_log_phase(trace_log, "stars.harmony_from_query_failed")
            pass
        try:
            _mark_request_log_phase(trace_log, "stars.harmony_to_query_start", detail={"anchors": len(anchor_ids)})
            to_rows = await self.supabase.query(
                STAR_LINK_TABLE,
                {
                    "select": "from_node_id,to_node_id,relation_type,confidence,weight,bidirectional,status",
                    "from_node_type": "eq.star",
                    "to_node_type": "eq.star",
                    "to_node_id": id_filter,
                    "status": "eq.active",
                    "limit": "500",
                },
            )
            rows.extend([row for row in to_rows if row.get("bidirectional")])
            _mark_request_log_phase(trace_log, "stars.harmony_to_query_done", detail={"rows": len(to_rows)})
        except Exception:
            _mark_request_log_phase(trace_log, "stars.harmony_to_query_failed")
            pass
        anchors = set(anchor_ids)
        scores: dict[str, float] = {}
        for row in rows:
            left = _node_id(row.get("from_node_id"))
            right = _node_id(row.get("to_node_id"))
            target = right if left in anchors else left if right in anchors and row.get("bidirectional") else ""
            if not target or target in anchors:
                continue
            relation_bonus = 1.0 if row.get("relation_type") == "constellation" else 0.75
            score = _clamp(_safe_float(row.get("confidence"), 0.5) * _safe_float(row.get("weight"), 1.0) * relation_bonus)
            scores[target] = max(scores.get(target, 0.0), score)
        return scores

    async def _activity_features(
        self,
        star_ids: list[str],
        *,
        include_recent_fatigue: bool = False,
        trace_log: Optional[dict] = None,
    ) -> tuple[dict[str, float], dict[str, float], set[str], dict[str, float]]:
        if not star_ids:
            return {}, {}, set(), {}
        if include_recent_fatigue:
            _mark_request_log_phase(trace_log, "stars.recent_fatigue_start", detail={"star_ids": len(star_ids)})
            recent_fatigue = await self._recent_fatigue_scores(star_ids)
            _mark_request_log_phase(trace_log, "stars.recent_fatigue_done", detail={"scores": len(recent_fatigue)})
        else:
            recent_fatigue = {}
        _mark_request_log_phase(trace_log, "stars.actr_start", detail={"star_ids": len(star_ids)})
        actr_scores = await self._actr_scores(star_ids)
        _mark_request_log_phase(trace_log, "stars.actr_done", detail={"scores": len(actr_scores)})
        _mark_request_log_phase(trace_log, "stars.ignored_penalties_start", detail={"star_ids": len(star_ids)})
        ignored_penalties, negative_set = await self._ignored_penalties(star_ids)
        _mark_request_log_phase(trace_log, "stars.ignored_penalties_done", detail={"scores": len(ignored_penalties)})
        return actr_scores, ignored_penalties, negative_set, recent_fatigue

    async def _actr_scores(self, star_ids: list[str]) -> dict[str, float]:
        try:
            rows = await self.supabase.query(
                STAR_ACTIVATION_TABLE,
                {
                    "select": "star_id,activated_at",
                    "star_id": "in.(" + ",".join(star_ids) + ")",
                    "order": "activated_at.desc",
                    "limit": str(min(max(len(star_ids) * 30, 100), 5000)),
                },
            )
        except Exception:
            return {}
        now_dt = _now()
        sums: dict[str, float] = {}
        for row in rows:
            star_id = _node_id(row.get("star_id"))
            dt = _parse_ts(row.get("activated_at"))
            if not star_id or not dt:
                continue
            age_days = max((now_dt - dt).total_seconds() / 86400.0, 0.05)
            sums[star_id] = sums.get(star_id, 0.0) + math.pow(age_days, -0.5)
        scores = {}
        for star_id, total in sums.items():
            if total <= 0:
                continue
            base = math.log(total)
            scores[star_id] = _clamp((base + 2.5) / 4.5)
        return scores

    async def _ignored_penalties(self, star_ids: list[str]) -> tuple[dict[str, float], set[str]]:
        try:
            rows = await self.supabase.query(
                STAR_CANDIDATE_TABLE,
                {
                    "select": "candidate_node_id,shown,action_status,created_at",
                    "candidate_node_type": "eq.star",
                    "candidate_node_id": "in.(" + ",".join(star_ids) + ")",
                    "shown": "eq.true",
                    "order": "created_at.desc",
                    "limit": str(min(max(len(star_ids) * 8, 100), 5000)),
                },
            )
        except Exception:
            return {}, set()
        by_star: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_star.setdefault(_node_id(row.get("candidate_node_id")), []).append(row)
        penalties: dict[str, float] = {}
        negative_set: set[str] = set()
        for star_id, history in by_star.items():
            latest = history[:5]
            actions = [(row.get("action_status") or "").strip().lower() for row in latest]
            if any(action == "negative" for action in actions):
                penalties[star_id] = 1.0
                negative_set.add(star_id)
                continue
            if any(action in POSITIVE_FEEDBACK for action in actions):
                continue
            silent_count = sum(1 for a in actions if a in ("", "skipped"))
            penalty = max(0.0, silent_count * 0.15 - 0.15)
            if penalty > 0:
                penalties[star_id] = min(penalty, 0.60)
        return penalties, negative_set

    async def _recent_fatigue_scores(self, star_ids: list[str]) -> dict[str, float]:
        hours = _safe_int(getattr(self.cfg, "star_recent_fatigue_hours", 6), 6, 0, 168)
        if hours <= 0:
            return {}
        try:
            rows = await self.supabase.query(
                STAR_ACTIVATION_TABLE,
                {
                    "select": "star_id,activated_at,injected",
                    "star_id": "in.(" + ",".join(star_ids) + ")",
                    "injected": "eq.true",
                    "order": "activated_at.desc",
                    "limit": str(min(max(len(star_ids) * 6, 100), 3000)),
                },
            )
        except Exception:
            return {}
        now_dt = _now()
        scores: dict[str, float] = {}
        window_seconds = max(hours * 3600.0, 1.0)
        for row in rows:
            star_id = _node_id(row.get("star_id"))
            dt = _parse_ts(row.get("activated_at"))
            if not star_id or not dt or star_id in scores:
                continue
            age_seconds = (now_dt - dt).total_seconds()
            if age_seconds < 0 or age_seconds > window_seconds:
                continue
            scores[star_id] = self._recent_fatigue_penalty() * (1.0 - age_seconds / window_seconds)
        return scores
