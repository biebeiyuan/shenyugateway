from __future__ import annotations

from typing import Any, Optional

from ..recall import recall_terms
from ..request_logs import _mark_request_log_phase
from ..runtime import iso_now, logger, now as _now
from ._chord import _chord_parts, _split_chord_sequence
from ._helpers import (
    _cfg_float, _json_dict, _node_id, _id_list, _safe_int, _safe_float,
    _star_search_text, _token_overlap,
    parse_star_payload, STAR_TABLE, STAR_LINK_TABLE, STAR_SELECT,
    STAR_RANKER_VERSION,
)
from ._scene import _classify_scene_by_keywords, _classify_scene_by_embedding, _load_scene_config
from ._weights import StarWeights


class CrudMixin:
    def __init__(self, cfg: Any, supabase_client: Any):
        self.cfg = cfg
        self.supabase = supabase_client

    def _weights(self) -> StarWeights:
        return StarWeights(
            ch_content=_safe_float(getattr(self.cfg, "star_rrf_ch_content", 1.0), 1.0),
            ch_keyword=_safe_float(getattr(self.cfg, "star_rrf_ch_keyword", 0.8), 0.8),
            ch_chord=_safe_float(getattr(self.cfg, "star_rrf_ch_chord", 0.6), 0.6),
            ch_harmony=_safe_float(getattr(self.cfg, "star_rrf_ch_harmony", 0.7), 0.7),
            ch_scene=_safe_float(getattr(self.cfg, "star_rrf_ch_scene", 0.4), 0.4),
            ch_explicit=_safe_float(getattr(self.cfg, "star_rrf_ch_explicit", 0.5), 0.5),
            rrf_k=_safe_int(getattr(self.cfg, "star_rrf_k", 60), 60, 1, 1000),
            actr_floor=_safe_float(getattr(self.cfg, "star_rrf_actr_floor", 0.5), 0.5),
            constant_boost=_safe_float(getattr(self.cfg, "star_rrf_constant_boost", 1.3), 1.3),
            date_boost_max=_safe_float(getattr(self.cfg, "star_rrf_date_boost_max", 0.3), 0.3),
        )

    def _candidate_limit(self) -> int:
        return _safe_int(getattr(self.cfg, "star_candidate_limit", 500), 500, 50, 5000)

    def _inject_limit(self, limit: Optional[int] = None) -> int:
        configured = getattr(self.cfg, "star_inject_limit", 3)
        return _safe_int(limit if limit is not None else configured, 3, 1, 5)

    def _min_score(self) -> float:
        return _cfg_float(self.cfg, "star_min_score", 0.18)

    def _related_min_score(self) -> float:
        return _cfg_float(self.cfg, "star_related_min_score", 0.22)

    def _recent_fatigue_penalty(self) -> float:
        return _cfg_float(self.cfg, "star_recent_fatigue_penalty", 0.14)

    def _scene_config(self) -> tuple[list[dict[str, Any]], dict[str, str], float]:
        path = getattr(self.cfg, "star_scene_rules_path", "") or ""
        return _load_scene_config(path)

    async def _classify_scene(self, query: str, *, trace_log: Optional[dict] = None) -> str:
        rules, descriptions, threshold = self._scene_config()
        scene = _classify_scene_by_keywords(query, rules)
        if scene:
            _mark_request_log_phase(trace_log, "stars.scene_classified", detail={"scene": scene, "method": "keywords"})
            return scene
        _mark_request_log_phase(trace_log, "stars.scene_keyword_miss", detail={"fallback": "embedding"})
        client = self._embedding_client()
        override_threshold = _safe_float(getattr(self.cfg, "star_scene_embedding_threshold", threshold), threshold)
        scene = await _classify_scene_by_embedding(query, descriptions, client, override_threshold)
        if scene:
            _mark_request_log_phase(trace_log, "stars.scene_classified", detail={"scene": scene, "method": "embedding"})
        else:
            scene = "daily"
            _mark_request_log_phase(trace_log, "stars.scene_classified", detail={"scene": scene, "method": "default"})
        return scene

    async def create_star(
        self,
        content: Any,
        *,
        chord: str = "",
        chords: Optional[list[str]] = None,
        session_tag: Optional[str] = None,
        status: str = "active",
        is_constant: bool = False,
        source_model: str = "tool:shenyu_create_star",
        source_session_id: Optional[str] = None,
        source_excerpt: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        parsed = parse_star_payload(content)
        star_content = (parsed.get("content") or "").strip()
        parsed_attrs = _json_dict(parsed.get("attrs"))
        chord_source = chords or parsed_attrs.get("chords") or parsed_attrs.get("chord_sequence") or chord or parsed.get("chord") or ""
        chord_sequence = _split_chord_sequence(chord_source)
        star_chord = (chord or parsed.get("chord") or "").strip()
        if len(chord_sequence) > 1:
            star_chord = " → ".join(chord_sequence)
        elif not star_chord and chord_sequence:
            star_chord = chord_sequence[0]
        if not star_content:
            return {"ok": False, "error": "content is required."}
        root, quality = _chord_parts(chord_sequence[0] if chord_sequence else star_chord)
        resolved_status = status if status in {"active", "paused", "archived"} else "active"
        meta = _json_dict(metadata)
        attrs = _json_dict(parsed.get("attrs"))
        if attrs:
            meta.setdefault("attrs", attrs)
        if len(chord_sequence) > 1:
            meta.setdefault("chord_sequence", chord_sequence)
        search_tokens = recall_terms("\n".join(part for part in [star_chord, " ".join(chord_sequence), star_content] if part))
        payload: dict[str, Any] = {
            "session_tag": (session_tag or "default").strip() or "default",
            "content": star_content,
            "chord": star_chord,
            "chord_root": root,
            "chord_quality": quality,
            "status": resolved_status,
            "is_constant": bool(is_constant),
            "source_model": source_model,
            "source_session_id": source_session_id,
            "source_excerpt": source_excerpt or "",
            "search_tokens": search_tokens,
            "metadata": meta,
        }
        await self._attach_embedding(payload, star_chord, star_content)
        row = await self.supabase.insert(STAR_TABLE, payload)
        if isinstance(row, dict):
            row = dict(row)
            row.setdefault("chord_sequence", chord_sequence if len(chord_sequence) > 1 else [])
        return {"ok": True, "star_id": row.get("id") if isinstance(row, dict) else None, "star": row}

    async def list_stars(
        self,
        *,
        status: str = "active",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        reviewed: str = "all",
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        status_key = (status or "active").strip().lower()
        params: dict[str, str] = {
            "select": STAR_SELECT,
            "order": "updated_at.desc",
            "limit": str(max(1, min(int(limit or 50), 200))),
        }
        if status_key != "all":
            params["status"] = f"eq.{status_key if status_key in {'active', 'paused', 'archived'} else 'active'}"
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        reviewed_key = (reviewed or "all").strip().lower()
        if reviewed_key in {"reviewed", "true", "yes"}:
            params["reviewed_at"] = "not.is.null"
        elif reviewed_key in {"unreviewed", "false", "no"}:
            params["reviewed_at"] = "is.null"
        rows = await self.supabase.query(STAR_TABLE, params)
        terms = recall_terms(q)
        if terms:
            rows = [
                row
                for row in rows
                if any(term in _star_search_text(row).lower() for term in terms)
            ]
        return {"ok": True, "count": len(rows), "items": [self._public_star(row) for row in rows]}

    async def search_stars(
        self,
        query: str,
        *,
        session_tag: Optional[str] = None,
        limit: int = 10,
        log_run: bool = False,
    ) -> dict[str, Any]:
        result = await self._rank_for_query(
            query=query,
            surface="manual_search",
            session_tag=session_tag,
            session_id=None,
            limit=max(1, min(int(limit or 10), 30)),
            shown=log_run,
            injected=False,
            mark_activation=False,
        )
        return {
            "ok": result.get("ok", False),
            "query": query,
            "count": len(result.get("items") or []),
            "items": result.get("items") or [],
            "run_id": result.get("run_id"),
            **({"error": result.get("error")} if result.get("error") else {}),
        }

    async def graph(
        self,
        *,
        status: str = "active",
        limit: int = 250,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "stars": [], "links": [], "error": "Supabase is not configured."}
        star_result = await self.list_stars(
            status=status,
            limit=max(1, min(int(limit or 250), 1000)),
            session_tag=session_tag,
            reviewed="all",
        )
        if not star_result.get("ok"):
            return {"ok": False, "stars": [], "links": [], "error": star_result.get("error") or "star query failed"}
        stars = star_result.get("items") or []
        star_ids = {_node_id(item.get("id")) for item in stars if item.get("id")}
        if not star_ids:
            return {"ok": True, "stars": [], "links": []}

        rows: list[dict[str, Any]] = []
        try:
            rows = await self.supabase.query(
                STAR_LINK_TABLE,
                {
                    "select": "id,from_node_type,from_node_id,to_node_type,to_node_id,relation_type,source,confidence,weight,position,bidirectional,times_confirmed,last_confirmed_at,metadata,status,created_at,updated_at",
                    "from_node_type": "eq.star",
                    "to_node_type": "eq.star",
                    "status": "eq.active",
                    "limit": "2000",
                },
            )
        except Exception as exc:
            logger.warning("[Star] Failed to load graph links: %s", exc)
            rows = []

        links = []
        for row in rows:
            left = _node_id(row.get("from_node_id"))
            right = _node_id(row.get("to_node_id"))
            if left not in star_ids or right not in star_ids:
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            links.append(
                {
                    "id": row.get("id"),
                    "source": left,
                    "target": right,
                    "relation_type": row.get("relation_type") or "manual",
                    "confidence": _safe_float(row.get("confidence"), 0.5),
                    "weight": _safe_float(row.get("weight"), 1.0),
                    "position": row.get("position"),
                    "bidirectional": bool(row.get("bidirectional")),
                    "times_confirmed": int(row.get("times_confirmed") or 0),
                    "last_confirmed_at": row.get("last_confirmed_at"),
                    "name": metadata.get("constellation_name") or "",
                    "note": metadata.get("note") or "",
                    "scored_by": metadata.get("scored_by") or "",
                }
            )
        return {"ok": True, "stars": stars, "links": links}

    async def search_context(
        self,
        query: str,
        *,
        session_tag: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: Optional[int] = None,
        trace_log: Optional[dict] = None,
    ) -> dict[str, Any]:
        if not getattr(self.cfg, "inject_stars", True):
            return {"ok": True, "query": query, "count": 0, "items": []}
        _mark_request_log_phase(
            trace_log,
            "stars.search_context_start",
            detail={"limit": self._inject_limit(limit), "query_chars": len(query or "")},
        )
        return await self._rank_for_query(
            query=query,
            surface="chat_inject",
            session_tag=session_tag,
            session_id=session_id,
            limit=self._inject_limit(limit),
            shown=True,
            injected=True,
            mark_activation=True,
            trace_log=trace_log,
        )

    async def connect_constellation(
        self,
        star_ids: Any,
        *,
        name: str = "",
        relation_type: str = "constellation",
        scored_by: str = "沈予",
        note: str = "",
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        ids = _id_list(star_ids)
        if len(ids) < 2:
            return {"ok": False, "error": "at least two star ids are required."}
        relation = relation_type if relation_type in {"constellation", "harmony", "keyword", "manual", "heartbeat"} else "constellation"
        metadata = {
            "constellation_name": (name or "").strip(),
            "scored_by": (scored_by or "沈予").strip() or "沈予",
            "note": (note or "").strip(),
            "sequence_mode": "entered_order",
        }
        rows = []
        for idx in range(len(ids) - 1):
            left = ids[idx]
            right = ids[idx + 1]
            if left == right:
                continue
            rows.append(
                {
                    "from_node_type": "star",
                    "from_node_id": left,
                    "to_node_type": "star",
                    "to_node_id": right,
                    "relation_type": relation,
                    "source": "shenyu",
                    "confidence": 1.0,
                    "weight": 1.0,
                    "position": idx,
                    "bidirectional": True,
                    "status": "active",
                    "times_confirmed": 1,
                    "last_confirmed_at": iso_now(),
                    "metadata": metadata,
                }
            )
        if not rows:
            return {"ok": False, "error": "no valid edges to connect."}
        if hasattr(self.supabase, "upsert"):
            result = await self.supabase.upsert(STAR_LINK_TABLE, rows, on_conflict="from_node_type,from_node_id,to_node_type,to_node_id,relation_type")
        else:
            result = []
            for row in rows:
                result.append(await self.supabase.insert(STAR_LINK_TABLE, row))
        return {"ok": True, "edge_count": len(rows), "links": result, "star_ids": ids}

    async def mark_constant(self, star_id: str, is_constant: bool = True) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        star_id = _node_id(star_id)
        if not star_id:
            return {"ok": False, "error": "star_id is required."}
        rows = await self.supabase.update(STAR_TABLE, {"id": star_id}, {"is_constant": bool(is_constant)})
        return {"ok": True, "star_id": star_id, "updated": rows}

    async def archive_star(self, star_id: str) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        star_id = _node_id(star_id)
        if not star_id:
            return {"ok": False, "error": "star_id is required."}
        rows = await self.supabase.update(STAR_TABLE, {"id": star_id}, {"status": "archived"})
        if not rows:
            return {"ok": False, "error": f"Star not found: {star_id}"}
        return {"ok": True, "star_id": star_id, "status": "archived"}

    async def merge_stars(
        self,
        source_ids: list[str],
        *,
        content: str = "",
        chord: str = "",
        is_constant: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        ids = [_node_id(sid) for sid in (source_ids or [])]
        ids = [sid for sid in ids if sid]
        if len(ids) < 2:
            return {"ok": False, "error": "At least 2 source star IDs required."}
        content = (content or "").strip()
        if not content:
            return {"ok": False, "error": "content is required for the merged star."}

        source_rows = await self.supabase.query(STAR_TABLE, {
            "select": STAR_SELECT,
            "id": f"in.({','.join(ids)})",
            "status": "eq.active",
        })
        found_ids = {str(r.get("id")) for r in source_rows}
        missing = [sid for sid in ids if sid not in found_ids]
        if missing:
            return {"ok": False, "error": f"Stars not found or not active: {missing}"}

        merge_meta = _json_dict(metadata)
        merge_meta["merged_from"] = ids

        created = await self.create_star(
            content,
            chord=chord,
            is_constant=is_constant,
            metadata=merge_meta,
            source_model="tool:shenyu_merge_stars",
        )
        if not created.get("ok"):
            return created
        new_star_id = created["star_id"]

        links_transferred = 0
        id_filter = f"in.({','.join(ids)})"
        outgoing = await self.supabase.query(STAR_LINK_TABLE, {
            "select": "*",
            "from_node_id": id_filter,
            "status": "eq.active",
        })
        incoming = await self.supabase.query(STAR_LINK_TABLE, {
            "select": "*",
            "to_node_id": id_filter,
            "status": "eq.active",
        })
        all_links = outgoing + incoming
        new_id_str = str(new_star_id)
        seen_edges: set[tuple[str, str, str]] = set()
        for link in all_links:
            from_id = str(link.get("from_node_id") or "")
            to_id = str(link.get("to_node_id") or "")
            rel = link.get("relation_type") or "harmony"
            new_from = new_id_str if from_id in found_ids else from_id
            new_to = new_id_str if to_id in found_ids else to_id
            if new_from == new_to:
                continue
            edge_key = (new_from, new_to, rel)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            try:
                await self.supabase.insert(STAR_LINK_TABLE, {
                    "from_node_type": "star",
                    "from_node_id": new_from,
                    "to_node_type": "star",
                    "to_node_id": new_to,
                    "relation_type": rel,
                    "source": "merge",
                    "bidirectional": link.get("bidirectional", True),
                    "weight": link.get("weight", 1.0),
                    "confidence": link.get("confidence", 0.5),
                    "status": "active",
                    "metadata": {"merged_from_link": str(link.get("id") or "")},
                })
                links_transferred += 1
            except Exception:
                pass

        for sid in ids:
            row = next((r for r in source_rows if str(r.get("id")) == sid), None)
            old_meta = _json_dict(row.get("metadata") if row else None)
            old_meta["merged_into"] = new_id_str
            await self.supabase.update(STAR_TABLE, {"id": sid}, {"status": "archived", "metadata": old_meta})

        await self.supabase.update(STAR_LINK_TABLE, {"from_node_id": id_filter, "status": "eq.active"}, {"status": "archived"})
        await self.supabase.update(STAR_LINK_TABLE, {"to_node_id": id_filter, "status": "eq.active"}, {"status": "archived"})

        return {
            "ok": True,
            "new_star": created.get("star"),
            "new_star_id": new_id_str,
            "archived_ids": ids,
            "links_transferred": links_transferred,
        }
