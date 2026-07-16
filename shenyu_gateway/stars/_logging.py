from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from ..request_logs import _mark_request_log_phase
from ..runtime import iso_now, logger
from ..utils import shorten as _shorten
from ._helpers import (
    STAR_RUN_TABLE, STAR_CANDIDATE_TABLE, STAR_ACTIVATION_TABLE, STAR_TABLE,
    STAR_RANKER_VERSION, STAR_FEATURE_SCHEMA_VERSION, STAR_WEIGHTS_VERSION,
    _node_id, _safe_int,
)


class LoggingMixin:

    async def _log_run_and_candidates(
        self,
        *,
        surface: str,
        trigger_text: str,
        seed: Optional[dict[str, Any]],
        session_tag: Optional[str],
        session_id: Optional[str],
        limit_requested: int,
        query_embedding_status: str,
        scored: list[dict[str, Any]],
        selected_ids: set[Any],
        shown: bool,
        injected: bool,
        trace_log: Optional[dict] = None,
    ) -> Optional[str]:
        shadow_limit = _safe_int(getattr(self.cfg, "star_shadow_candidate_limit", 20), 20, 3, 100)
        try:
            _mark_request_log_phase(trace_log, "stars.run_insert_start", detail={"scored": len(scored)})
            run = await self.supabase.insert(
                STAR_RUN_TABLE,
                {
                    "surface": surface,
                    "trigger_text": trigger_text or "",
                    "seed_node_type": "star" if seed and seed.get("id") else None,
                    "seed_node_id": _node_id(seed.get("id")) if seed and seed.get("id") else None,
                    "session_tag": session_tag,
                    "session_id": session_id,
                    "limit_requested": limit_requested,
                    "ranker_version": STAR_RANKER_VERSION,
                    "feature_schema_version": STAR_FEATURE_SCHEMA_VERSION,
                    "weights_version": STAR_WEIGHTS_VERSION,
                    "query_embedding_status": query_embedding_status,
                    "metadata": {"weights": self._weights().__dict__},
                },
            )
            run_id = run.get("id") if isinstance(run, dict) else None
            _mark_request_log_phase(trace_log, "stars.run_insert_done", detail={"run_logged": bool(run_id)})
        except Exception as exc:
            logger.warning("[Star] failed to create recall run: %s", exc)
            _mark_request_log_phase(trace_log, "stars.run_insert_failed", detail={"error": _shorten(str(exc), 240)})
            return None
        if not run_id:
            return None
        rows = []
        for rank, item in enumerate(scored[:shadow_limit], start=1):
            star_id = _node_id(item["row"].get("id"))
            selected = item["row"].get("id") in selected_ids or star_id in selected_ids
            features = item.get("features") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "candidate_node_type": "star",
                    "candidate_node_id": star_id,
                    "rank": rank,
                    "shown": bool(shown and selected),
                    "injected": bool(injected and selected),
                    "final_score": item.get("final_score") or 0.0,
                    "content_score": features.get("content_score") or 0.0,
                    "keyword_score": features.get("keyword_score") or 0.0,
                    "chord_score": features.get("chord_score") or 0.0,
                    "harmony_score": features.get("harmony_score") or 0.0,
                    "content_gravity_score": features.get("content_gravity_score") or 0.0,
                    "actr_score": features.get("actr_score") or 0.0,
                    "constant_bonus": features.get("constant_bonus") or 0.0,
                    "novelty_bonus": features.get("novelty_bonus") or 0.0,
                    "ignored_penalty": features.get("ignored_penalty") or 0.0,
                    "feature_json": {
                        "ranker_version": STAR_RANKER_VERSION,
                        "direct_reference_kind": str(item.get("direct_reference_kind") or ""),
                        "direct_reference_count": 1 if item.get("direct_reference_kind") else 0,
                        "keyword_hits": item.get("keyword_hits") or [],
                        "explicit_hits": item.get("explicit_hits") or [],
                        "related_signal": features.get("related_signal") or 0.0,
                        "explicit_mention": features.get("explicit_mention") or 0.0,
                        "recent_fatigue_penalty": features.get("recent_fatigue_penalty") or 0.0,
                        "rrf_score": features.get("rrf_score") or 0.0,
                        "rrf_contributions": features.get("rrf_contributions") or {},
                        "actr_modifier": features.get("actr_modifier") or 0.0,
                        "novelty_modifier": features.get("novelty_modifier") or 0.0,
                        "constant_modifier": features.get("constant_modifier") or 0.0,
                        "fatigue_modifier": features.get("fatigue_modifier") or 0.0,
                        "date_modifier": features.get("date_modifier") or 0.0,
                    },
                }
            )
        if rows:
            try:
                _mark_request_log_phase(trace_log, "stars.candidates_insert_start", detail={"rows": len(rows)})
                inserted = await self.supabase.insert_many(STAR_CANDIDATE_TABLE, rows)
                inserted_by_star = {
                    _node_id(row.get("candidate_node_id")): row.get("id")
                    for row in inserted or []
                    if isinstance(row, dict)
                }
                for item in scored[:shadow_limit]:
                    star_id = _node_id(item["row"].get("id"))
                    if star_id in inserted_by_star:
                        item["candidate_id"] = inserted_by_star[star_id]
                _mark_request_log_phase(
                    trace_log,
                    "stars.candidates_insert_done",
                    detail={"rows": len(inserted or [])},
                )
            except Exception as exc:
                logger.warning("[Star] failed to log candidates: %s", exc)
                _mark_request_log_phase(
                    trace_log,
                    "stars.candidates_insert_failed",
                    detail={"error": _shorten(str(exc), 240)},
                )
        return run_id

    async def _mark_activated(
        self,
        selected: list[dict[str, Any]],
        *,
        run_id: Optional[str],
        surface: str,
        trigger_text: str,
        session_tag: Optional[str],
        session_id: Optional[str],
        injected: bool,
        trace_log: Optional[dict] = None,
    ) -> None:
        now_text = iso_now()
        rows = []
        for item in selected:
            star_id = _node_id(item["row"].get("id"))
            if not star_id:
                continue
            rows.append(
                {
                    "star_id": star_id,
                    "run_id": run_id,
                    "surface": surface,
                    "trigger_text": trigger_text or "",
                    "score": item.get("final_score") or 0.0,
                    "injected": injected,
                    "session_tag": session_tag,
                    "session_id": session_id,
                }
            )
        if rows:
            try:
                _mark_request_log_phase(trace_log, "stars.activation_insert_start", detail={"rows": len(rows)})
                await self.supabase.insert_many(STAR_ACTIVATION_TABLE, rows)
                _mark_request_log_phase(trace_log, "stars.activation_insert_done", detail={"rows": len(rows)})
            except Exception as exc:
                logger.warning("[Star] failed to insert activations: %s", exc)
                _mark_request_log_phase(
                    trace_log,
                    "stars.activation_insert_failed",
                    detail={"error": _shorten(str(exc), 240)},
                )
        for item in selected:
            row = item["row"]
            star_id = _node_id(row.get("id"))
            if not star_id:
                continue
            try:
                _mark_request_log_phase(trace_log, "stars.activation_update_start", detail={"star_id": star_id})
                await self.supabase.update(
                    STAR_TABLE,
                    {"id": star_id},
                    {
                        "activation_count": int(row.get("activation_count") or 0) + 1,
                        "last_activated_at": now_text,
                    },
                )
                _mark_request_log_phase(trace_log, "stars.activation_update_done", detail={"star_id": star_id})
            except Exception as exc:
                logger.warning("[Star] failed to mark activation: id=%s error=%s", star_id, exc)
                _mark_request_log_phase(
                    trace_log,
                    "stars.activation_update_failed",
                    detail={"star_id": star_id, "error": _shorten(str(exc), 240)},
                )
