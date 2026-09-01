from __future__ import annotations

import math
from typing import Any, Optional

from ..request_logs import _mark_request_log_phase
from ..runtime import now as _now
from ._helpers import (
    _clamp, _json_dict, _node_id, _safe_float, _safe_int,
    _token_overlap, _star_search_text, _significant_hit, _direct_reference_kinds, _query_star_ids,
    STAR_TABLE, STAR_LINK_TABLE, STAR_SELECT,
    STAR_CANDIDATE_TABLE, STAR_RUN_TABLE,
    STAR_RANKER_VERSION, STAR_FEATURE_SCHEMA_VERSION,
    DIRECT_REFERENCE_HARD_KINDS, DIRECT_REFERENCE_SOFT_KIND,
)
from ._chord import _chord_similarity, _extract_chord_from_query
from ._scene import _scene_score, _date_anchor_score


class RecallMixin:
    async def _rank_for_query(
        self,
        *,
        query: str,
        surface: str,
        session_tag: Optional[str],
        session_id: Optional[str],
        limit: int,
        shown: bool,
        injected: bool,
        mark_activation: bool,
        ignore_recent_fatigue: bool = False,
        required_star_ids: Optional[set[str]] = None,
        trace_log: Optional[dict] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {
                "ok": False,
                "query": query,
                "count": 0,
                "items": [],
                "_active_required_ids": [],
                "error": "Supabase is not configured.",
            }
        clean_query = (query or "").strip()
        if not clean_query:
            return {"ok": True, "query": clean_query, "count": 0, "items": [], "_active_required_ids": []}
        _mark_request_log_phase(
            trace_log,
            "stars.rank_start",
            detail={"surface": surface, "query_chars": len(clean_query), "limit": limit},
        )
        rows, query_embedding_status, active_required_ids = await self._candidate_rows(
            clean_query,
            required_star_ids=required_star_ids,
            trace_log=trace_log,
        )
        _mark_request_log_phase(
            trace_log,
            "stars.candidates_done",
            detail={"rows": len(rows), "query_embedding_status": query_embedding_status},
        )
        if not rows:
            return {
                "ok": True,
                "query": clean_query,
                "count": 0,
                "items": [],
                "_active_required_ids": sorted(active_required_ids),
            }
        direct_reference_kinds = _direct_reference_kinds(clean_query, rows) if surface == "chat_inject" else {}
        _mark_request_log_phase(
            trace_log,
            "stars.direct_reference_done",
            detail={
                "hard": sum(1 for kind in direct_reference_kinds.values() if kind in DIRECT_REFERENCE_HARD_KINDS),
                "soft": sum(1 for kind in direct_reference_kinds.values() if kind == DIRECT_REFERENCE_SOFT_KIND),
            },
        )
        scored = await self._score_rows(
            query=clean_query,
            rows=rows,
            seed=None,
            surface=surface,
            ignore_recent_fatigue=ignore_recent_fatigue,
            direct_reference_kinds=direct_reference_kinds,
            trace_log=trace_log,
        )
        _mark_request_log_phase(trace_log, "stars.score_done", detail={"scored": len(scored)})
        selected = await self._select_for_surface(scored, limit=max(1, min(int(limit or 3), 30)), surface=surface)
        run_id = await self._log_run_and_candidates(
            surface=surface,
            trigger_text=clean_query,
            seed=None,
            session_tag=session_tag,
            session_id=session_id,
            limit_requested=limit,
            query_embedding_status=query_embedding_status,
            scored=scored,
            selected_ids={item["row"].get("id") for item in selected},
            shown=shown,
            injected=injected,
            trace_log=trace_log,
        )
        _mark_request_log_phase(
            trace_log,
            "stars.log_run_done",
            detail={"selected": len(selected), "run_logged": bool(run_id)},
        )
        if mark_activation and selected:
            await self._mark_activated(
                selected,
                run_id=run_id,
                surface=surface,
                trigger_text=clean_query,
                session_tag=session_tag,
                session_id=session_id,
                injected=injected,
                trace_log=trace_log,
            )
            _mark_request_log_phase(trace_log, "stars.activation_done", detail={"selected": len(selected)})
        items = [self._public_candidate(item, run_id=run_id) for item in selected]
        _mark_request_log_phase(trace_log, "stars.search_context_done", detail={"items": len(items)})
        return {
            "ok": True,
            "query": clean_query,
            "count": len(items),
            "items": items,
            "run_id": run_id,
            "_active_required_ids": sorted(active_required_ids),
        }

    async def _rank_for_seed(
        self,
        seed: dict[str, Any],
        *,
        surface: str,
        session_tag: Optional[str],
        limit: int,
        shown: bool,
        exclude_node_ids: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        rows, query_embedding_status, _active_required_ids = await self._candidate_rows(seed.get("content") or "")
        seed_id = _node_id(seed.get("id"))
        excluded = {_node_id(item) for item in (exclude_node_ids or set()) if _node_id(item)}
        rows = [row for row in rows if _node_id(row.get("id")) != seed_id and _node_id(row.get("id")) not in excluded]
        scored = await self._score_rows(query=seed.get("content") or "", rows=rows, seed=seed, surface=surface)
        selected = await self._select_for_surface(scored, limit=max(1, min(int(limit or 3), 10)), surface=surface)
        run_id = await self._log_run_and_candidates(
            surface=surface,
            trigger_text=seed.get("content") or "",
            seed=seed,
            session_tag=session_tag,
            session_id=None,
            limit_requested=limit,
            query_embedding_status=query_embedding_status,
            scored=scored,
            selected_ids={item["row"].get("id") for item in selected},
            shown=shown,
            injected=False,
        )
        return {
            "ok": True,
            "count": len(selected),
            "items": [self._public_candidate(item, run_id=run_id) for item in selected],
            "run_id": run_id,
        }

    async def _candidate_rows(
        self,
        query: str,
        *,
        required_star_ids: Optional[set[str]] = None,
        trace_log: Optional[dict] = None,
    ) -> tuple[list[dict[str, Any]], str, set[str]]:
        required_ids = {_node_id(item) for item in (required_star_ids or set()) if _node_id(item)}
        lookup_ids = required_ids | _query_star_ids(query)
        params = {
            "select": STAR_SELECT,
            "status": "eq.active",
            "order": "is_constant.desc,last_activated_at.desc,updated_at.desc",
            "limit": str(self._candidate_limit()),
        }
        _mark_request_log_phase(
            trace_log,
            "stars.candidates_query_start",
            detail={"limit": self._candidate_limit()},
        )
        rows = await self.supabase.query(STAR_TABLE, params)
        _mark_request_log_phase(trace_log, "stars.candidates_query_done", detail={"rows": len(rows)})
        rows_by_id = {_node_id(row.get("id")): dict(row) for row in rows if row.get("id")}
        missing_required = lookup_ids - set(rows_by_id)
        if missing_required:
            required_rows = await self.supabase.query(
                STAR_TABLE,
                {
                    "select": STAR_SELECT,
                    "id": "in.(" + ",".join(sorted(missing_required)) + ")",
                    "status": "eq.active",
                    "limit": str(len(missing_required)),
                },
            )
            rows_by_id.update(
                {_node_id(row.get("id")): dict(row) for row in required_rows if row.get("id")}
            )
        active_required_ids = required_ids & set(rows_by_id)
        embedding_status = "skipped"
        vector_rows = await self._vector_rows(query, trace_log=trace_log)
        if vector_rows:
            embedding_status = "used"
        for row in vector_rows:
            star_id = _node_id(row.get("id"))
            if not star_id:
                continue
            existing = rows_by_id.get(star_id, {})
            existing.update(row)
            existing["_vector_score"] = _safe_float(row.get("vector_score"), 0.0)
            rows_by_id[star_id] = existing
        return list(rows_by_id.values()), embedding_status, active_required_ids

    async def _select_for_surface(self, scored: list[dict[str, Any]], *, limit: int, surface: str) -> list[dict[str, Any]]:
        if surface == "chat_inject":
            return await self._select_for_chat_inject(scored, limit=limit)
        return self._select_for_review(scored, limit=limit)

    async def _select_for_chat_inject(self, scored: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        min_score = self._min_score()
        related_min = self._related_min_score()
        direct = [item for item in scored if item.get("direct_reference_kind")]
        direct_ids = {_node_id(item.get("row", {}).get("id")) for item in direct}
        primary = [
            item
            for item in scored
            if float(item.get("final_score") or 0.0) >= min_score
            and float((item.get("features") or {}).get("related_signal") or 0.0) >= related_min
            and _node_id(item.get("row", {}).get("id")) not in direct_ids
        ]
        if not primary and not direct:
            fallback_limit = _safe_int(getattr(self.cfg, "star_chat_explicit_fallback_limit", 1), 1, 0, 3)
            if fallback_limit > 0:
                primary = [
                    item
                    for item in scored
                    if float((item.get("features") or {}).get("explicit_score") or 0.0) > 0
                ][: min(limit, fallback_limit)]
        selected = direct[:limit]
        selected_ids = {_node_id(item.get("row", {}).get("id")) for item in selected}
        selected.extend(
            item
            for item in primary
            if _node_id(item.get("row", {}).get("id")) not in selected_ids
        )
        selected = selected[:limit]
        if not selected:
            return []
        remaining_slots = limit - len(selected)
        if remaining_slots > 0:
            selected_ids = {_node_id(item["row"].get("id")) for item in selected if item.get("row")}
            pulled = await self._constellation_pull(selected_ids, scored, exclude=selected_ids)
            selected.extend(pulled[:remaining_slots])
        selected.sort(key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
        return selected[:limit]

    async def _constellation_pull(
        self,
        anchor_ids: set[str],
        all_scored: list[dict[str, Any]],
        exclude: set[str],
    ) -> list[dict[str, Any]]:
        if not anchor_ids:
            return []
        id_filter = "in.(" + ",".join(anchor_ids) + ")"
        linked_ids: set[str] = set()
        try:
            from_rows = await self.supabase.query(
                STAR_LINK_TABLE,
                {
                    "select": "from_node_id,to_node_id,relation_type,bidirectional",
                    "from_node_type": "eq.star",
                    "to_node_type": "eq.star",
                    "from_node_id": id_filter,
                    "relation_type": "in.(constellation,harmony)",
                    "status": "eq.active",
                    "limit": "200",
                },
            )
            for row in from_rows:
                target = _node_id(row.get("to_node_id"))
                if target and target not in exclude:
                    linked_ids.add(target)
        except Exception:
            pass
        try:
            to_rows = await self.supabase.query(
                STAR_LINK_TABLE,
                {
                    "select": "from_node_id,to_node_id,relation_type,bidirectional",
                    "from_node_type": "eq.star",
                    "to_node_type": "eq.star",
                    "to_node_id": id_filter,
                    "relation_type": "in.(constellation,harmony)",
                    "status": "eq.active",
                    "bidirectional": "eq.true",
                    "limit": "200",
                },
            )
            for row in to_rows:
                target = _node_id(row.get("from_node_id"))
                if target and target not in exclude:
                    linked_ids.add(target)
        except Exception:
            pass
        if not linked_ids:
            return []
        pulled = [
            item for item in all_scored
            if _node_id(item.get("row", {}).get("id")) in linked_ids
            and not item.get("features", {}).get("explicitly_negative")
            and float(item.get("final_score") or 0.0) >= 0
        ]
        pulled.sort(key=lambda x: float(x.get("final_score") or 0.0), reverse=True)
        return pulled

    def _select_for_review(self, scored: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        return scored[:limit]

    async def _score_rows(
        self,
        *,
        query: str,
        rows: list[dict[str, Any]],
        seed: Optional[dict[str, Any]],
        surface: str = "",
        ignore_recent_fatigue: bool = False,
        direct_reference_kinds: Optional[dict[str, str]] = None,
        trace_log: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        star_ids = [_node_id(row.get("id")) for row in rows if row.get("id")]
        _mark_request_log_phase(trace_log, "stars.activity_features_start", detail={"star_ids": len(star_ids)})
        actr_scores, ignored_penalties, negative_set, recent_fatigue = await self._activity_features(
            star_ids,
            include_recent_fatigue=surface == "chat_inject" and not ignore_recent_fatigue,
            trace_log=trace_log,
        )
        _mark_request_log_phase(
            trace_log,
            "stars.activity_features_done",
            detail={
                "actr": len(actr_scores),
                "ignored": len(ignored_penalties),
                "negative": len(negative_set),
                "recent_fatigue": len(recent_fatigue),
            },
        )
        seed_chord = seed or _extract_chord_from_query(query)
        query_scene = await self._classify_scene(query, trace_log=trace_log)
        direct_reference_kinds = direct_reference_kinds or {}
        now_dt = _now()
        base_items: list[dict[str, Any]] = []
        for row in rows:
            keyword_score, hits = _token_overlap(query, _star_search_text(row), row.get("search_tokens"))
            content_overlap, _ = _token_overlap(query, row.get("content") or "", row.get("search_tokens"))
            vector_score = _safe_float(row.get("_vector_score"), 0.0)
            content_score = max(content_overlap, vector_score)
            chord_score = _chord_similarity(seed_chord, row) if seed_chord else 0.0
            content_gravity = max(content_score, keyword_score)
            star_id = _node_id(row.get("id"))
            base_score = content_score * 0.55 + keyword_score * 0.25 + chord_score * 0.20
            star_meta = _json_dict(row.get("metadata"))
            scene_sc = _scene_score(
                query_scene,
                str(star_meta.get("scene") or ""),
                query,
                star_meta.get("scene_tags") or [],
            )
            date_sc = _date_anchor_score(star_meta, now_dt)
            explicit_hits = [hit for hit in hits if _significant_hit(hit)]
            explicit_sc = min(1.0, len(explicit_hits) * 0.5)
            direct_reference_kind = str(direct_reference_kinds.get(star_id) or "")
            if direct_reference_kind:
                explicit_sc = 1.0
            ignored_raw = ignored_penalties.get(star_id, 0.0)
            if row.get("is_constant"):
                ignored_raw = 0.0
            base_items.append(
                {
                    "row": row,
                    "keyword_hits": hits,
                    "explicit_hits": explicit_hits,
                    "direct_reference_kind": direct_reference_kind,
                    "base_score": base_score,
                    "features": {
                        "content_score": _clamp(content_score),
                        "keyword_score": _clamp(keyword_score),
                        "chord_score": _clamp(chord_score),
                        "harmony_score": 0.0,
                        "scene_score": _clamp(scene_sc),
                        "explicit_score": _clamp(explicit_sc),
                        "date_anchor_score": _clamp(date_sc),
                        "content_gravity_score": _clamp(content_gravity),
                        "actr_score": actr_scores.get(star_id, 0.0),
                        "constant_bonus": 1.0 if row.get("is_constant") else 0.0,
                        "novelty_bonus": 0.0 if row.get("activation_count") else 1.0,
                        "ignored_penalty": ignored_raw,
                        "recent_fatigue_penalty": recent_fatigue.get(star_id, 0.0),
                        "explicitly_negative": star_id in negative_set,
                    },
                }
            )
        anchors = self._anchor_ids(base_items, seed)
        _mark_request_log_phase(trace_log, "stars.harmony_start", detail={"anchors": len(anchors)})
        harmony_scores = await self._harmony_scores(anchors, trace_log=trace_log)
        _mark_request_log_phase(trace_log, "stars.harmony_done", detail={"scores": len(harmony_scores)})
        weights = self._weights()

        eligible: list[dict[str, Any]] = []
        for item in base_items:
            star_id = _node_id(item["row"].get("id"))
            features = dict(item["features"])
            features["harmony_score"] = max(features["harmony_score"], harmony_scores.get(star_id, 0.0))
            related_signal = max(
                features["content_score"],
                features["keyword_score"],
                features["chord_score"],
                features["harmony_score"],
                features["scene_score"],
                features["explicit_score"],
            )
            features["related_signal"] = related_signal
            features["explicit_mention"] = features["explicit_score"]
            item["features"] = features
            if related_signal <= 0 or (
                features.get("explicitly_negative") and not item.get("direct_reference_kind")
            ):
                continue
            eligible.append(item)

        channels = [
            ("content_score", weights.ch_content),
            ("keyword_score", weights.ch_keyword),
            ("chord_score", weights.ch_chord),
            ("harmony_score", weights.ch_harmony),
            ("scene_score", weights.ch_scene),
            ("explicit_score", weights.ch_explicit),
        ]
        k = weights.rrf_k
        rrf_by_star: dict[str, dict[str, float]] = {}
        for ch_key, ch_weight in channels:
            if ch_weight <= 0:
                continue
            active = [it for it in eligible if (it["features"].get(ch_key) or 0.0) > 0]
            active.sort(key=lambda x: x["features"][ch_key], reverse=True)
            for rank_0, it in enumerate(active):
                sid = _node_id(it["row"].get("id"))
                rrf_by_star.setdefault(sid, {})[ch_key] = ch_weight / (k + rank_0 + 1)

        scored: list[dict[str, Any]] = []
        for item in eligible:
            features = item["features"]
            star_id = _node_id(item["row"].get("id"))
            contribs = rrf_by_star.get(star_id, {})
            rrf_score = sum(contribs.values())

            actr_raw = features.get("actr_score", 0.0)
            actr_mod = weights.actr_floor + (1.0 - weights.actr_floor) * actr_raw

            act_count = item["row"].get("activation_count") or 0
            novelty_mod = 1.0 / (1.0 + math.log10(act_count + 1))

            constant_mod = weights.constant_boost if item["row"].get("is_constant") else 1.0

            fatigue_pen = features.get("recent_fatigue_penalty", 0.0)
            fatigue_mod = max(0.0, 1.0 - fatigue_pen)

            date_sc = features.get("date_anchor_score", 0.0)
            date_mod = 1.0 + weights.date_boost_max * date_sc

            final = rrf_score * actr_mod * novelty_mod * constant_mod * fatigue_mod * date_mod

            features["rrf_score"] = rrf_score
            features["rrf_contributions"] = contribs
            features["actr_modifier"] = actr_mod
            features["novelty_modifier"] = novelty_mod
            features["constant_modifier"] = constant_mod
            features["fatigue_modifier"] = fatigue_mod
            features["date_modifier"] = date_mod

            if final <= 0 and not seed:
                continue
            item["final_score"] = max(0.0, final)
            item["direct_reference_kind"] = str(item.get("direct_reference_kind") or "")
            scored.append(item)
        scored.sort(key=lambda item: item["final_score"], reverse=True)
        return scored

    def _anchor_ids(self, scored: list[dict[str, Any]], seed: Optional[dict[str, Any]]) -> list[str]:
        if seed and seed.get("id"):
            return [_node_id(seed.get("id"))]
        anchors = [
            item
            for item in scored
            if item["features"]["content_gravity_score"] >= 0.28 or item["features"]["chord_score"] >= 0.5
        ]
        anchors.sort(key=lambda item: item["base_score"], reverse=True)
        return [_node_id(item["row"].get("id")) for item in anchors[:5] if item["row"].get("id")]
