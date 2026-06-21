from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .embeddings import EmbeddingClient
from .recall import recall_terms
from .request_logs import _mark_request_log_phase
from .runtime import iso_now, logger, now as _now, parse_ts as _parse_ts
from .utils import normalize_text as _normalize_text
from .utils import shorten as _shorten


STAR_TABLE = "shenyu_stars"
STAR_LINK_TABLE = "shenyu_star_links"
STAR_RUN_TABLE = "shenyu_star_recall_runs"
STAR_CANDIDATE_TABLE = "shenyu_star_recall_candidates"
STAR_FEEDBACK_TABLE = "shenyu_star_feedback"
STAR_ACTIVATION_TABLE = "shenyu_star_activations"

STAR_RANKER_VERSION = "star-ranker-v0"
STAR_FEATURE_SCHEMA_VERSION = "star-features-v0"
STAR_WEIGHTS_VERSION = "manual-v0"

STAR_SELECT = (
    "id,session_tag,content,chord,chord_root,chord_quality,chord_tension,status,is_constant,"
    "reviewed_at,activation_count,last_activated_at,source_model,source_session_id,source_excerpt,"
    "search_tokens,embedding_model,embedding_status,metadata,created_at,updated_at"
)

POSITIVE_FEEDBACK = {"positive", "connected", "should_surface", "missed"}
NEGATIVE_FEEDBACK = {"negative", "skipped"}
FEEDBACK_VALUES = POSITIVE_FEEDBACK | NEGATIVE_FEEDBACK
ADMIN_SCORERS = {"圆圆", "圆儿", "admin"}
EXPLICIT_MENTION_STOPWORDS = {
    "一个",
    "不是",
    "不能",
    "今天",
    "什么",
    "但是",
    "你好",
    "可以",
    "只是",
    "因为",
    "如果",
    "就是",
    "我们",
    "所以",
    "时候",
    "明天",
    "昨天",
    "没有",
    "现在",
    "真的",
    "觉得",
    "这个",
    "这么",
    "那个",
    "一起",
    "and",
    "are",
    "but",
    "for",
    "not",
    "the",
    "you",
}


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(float(value or 0.0), max_value))


def _safe_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"value": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


def _node_id(value: Any) -> str:
    return str(value or "").strip()


def _id_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = re.split(r"[,，\s]+", value.strip())
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        star_id = _node_id(item)
        if star_id and star_id not in seen:
            seen.add(star_id)
            result.append(star_id)
    return result


def _star_search_text(row: dict[str, Any]) -> str:
    metadata = _json_dict(row.get("metadata"))
    return "\n".join(
        part
        for part in [
            str(row.get("content") or ""),
            str(row.get("chord") or ""),
            str(row.get("chord_root") or ""),
            str(row.get("chord_quality") or ""),
            " ".join(str(item) for item in row.get("search_tokens") or []),
            " ".join(str(value) for value in metadata.values()),
        ]
        if part
    )


def _token_overlap(query: str, text: str, row_tokens: Optional[list[Any]] = None) -> tuple[float, list[str]]:
    query_terms = recall_terms(query)
    if not query_terms:
        return 0.0, []
    hay = (text or "").lower()
    tokens = {str(item).strip().lower() for item in row_tokens or [] if str(item).strip()}
    hits = []
    for term in query_terms:
        if term in tokens or term in hay:
            hits.append(term)
    return _clamp(len(set(hits)) / max(len(set(query_terms)), 1)), hits


def _significant_hit(term: Any) -> bool:
    text = str(term or "").strip().lower()
    if not text:
        return False
    if text in EXPLICIT_MENTION_STOPWORDS:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]+", text):
        return len(text) >= 2
    return bool(re.search(r"[a-z0-9]", text)) and len(text) >= 3


def _chord_parts(chord: str) -> tuple[str, str]:
    clean = (chord or "").strip()
    if not clean:
        return "", ""
    clean = clean.replace("♭", "b").replace("♯", "#").replace("Δ", "maj")
    match = re.match(r"^\s*([A-Ga-g](?:#|b)?)(.*)$", clean)
    if not match:
        return "", ""
    root = match.group(1).upper()
    quality_raw = (match.group(2) or "").strip()
    quality_lower = quality_raw.lower()
    quality = ""
    if "dim" in quality_lower or "°" in quality_raw:
        quality = "dim"
    elif "aug" in quality_lower or "+" in quality_raw:
        quality = "aug"
    elif "sus" in quality_lower:
        quality = "sus"
    elif "maj" in quality_lower or quality_raw.startswith("M"):
        quality = "major"
    elif quality_lower.startswith("min") or quality_raw.startswith("m") or "-" in quality_raw:
        quality = "minor"
    elif "7" in quality_raw:
        quality = "dominant"
    return root, quality


def _chord_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_chord = str(left.get("chord") or "").strip().casefold()
    right_chord = str(right.get("chord") or "").strip().casefold()
    if left_chord and right_chord and left_chord == right_chord:
        return 1.0
    score = 0.0
    if left.get("chord_root") and left.get("chord_root") == right.get("chord_root"):
        score += 0.55
    if left.get("chord_quality") and left.get("chord_quality") == right.get("chord_quality"):
        score += 0.25
    return _clamp(score, 0.0, 0.85)


def _extract_chord_from_query(query: str) -> dict[str, str]:
    text = query or ""
    for match in re.finditer(r"\b([A-Ga-g](?:#|b)?(?:maj|min|m|dim|aug|sus|add)?[0-9#b+\-/]*)\b", text):
        chord = match.group(1).strip()
        root, quality = _chord_parts(chord)
        if root:
            return {"chord": chord, "chord_root": root, "chord_quality": quality}
    return {"chord": "", "chord_root": "", "chord_quality": ""}


def _split_chord_sequence(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts = [_node_id(item) for item in value]
        return [part for part in parts if part]
    text = _normalize_text(value).strip()
    if not text:
        return []
    normalized = (
        text.replace("→", "|")
        .replace("⇒", "|")
        .replace("->", "|")
        .replace("=>", "|")
        .replace("｜", "|")
        .replace("•", "|")
        .replace("·", "|")
        .replace("；", "|")
        .replace(";", "|")
        .replace("，", "|")
        .replace(",", "|")
        .replace("\n", "|")
    )
    normalized = re.sub(r"\s+/\s+", "|", normalized)
    parts = [part.strip() for part in normalized.split("|") if part.strip()]
    return parts if len(parts) > 1 else [text]


def parse_star_payload(star: Any) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if isinstance(star, dict):
        attrs.update(_json_dict(star.get("attrs")))
        content = _normalize_text(star.get("content")).strip()
        if star.get("chord") and not attrs.get("chord"):
            attrs["chord"] = star.get("chord")
        if star.get("chords") is not None and not attrs.get("chords"):
            attrs["chords"] = star.get("chords")
        if star.get("chord_sequence") is not None and not attrs.get("chord_sequence"):
            attrs["chord_sequence"] = star.get("chord_sequence")
    else:
        content = _normalize_text(star).strip()

    chord = _normalize_text(attrs.get("chord") or "").strip()
    if not chord and content:
        for delimiter in ("·", "•", "|", "｜"):
            if delimiter not in content:
                continue
            head, body = content.split(delimiter, 1)
            if 1 <= len(head.strip()) <= 32:
                chord = head.strip()
                content = body.strip()
                break
    root, quality = _chord_parts(chord)
    return {
        "content": content,
        "chord": chord,
        "chord_root": root,
        "chord_quality": quality,
        "attrs": attrs,
    }


@dataclass(frozen=True)
class StarWeights:
    content: float = 0.30
    keyword: float = 0.20
    harmony: float = 0.35
    chord: float = 0.18
    actr: float = 0.08
    constant_bonus: float = 0.08
    novelty_bonus: float = 0.04
    ignored_penalty: float = 0.18


def _cfg_float(cfg: Any, name: str, default: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return _clamp(_safe_float(getattr(cfg, name, default), default), min_value, max_value)


class StarService:
    def __init__(self, cfg: Any, supabase_client: Any):
        self.cfg = cfg
        self.supabase = supabase_client

    def _weights(self) -> StarWeights:
        return StarWeights(
            content=_safe_float(getattr(self.cfg, "star_weight_content", 0.30), 0.30),
            keyword=_safe_float(getattr(self.cfg, "star_weight_keyword", 0.20), 0.20),
            harmony=_safe_float(getattr(self.cfg, "star_weight_harmony", 0.35), 0.35),
            chord=_safe_float(getattr(self.cfg, "star_weight_chord", 0.18), 0.18),
            actr=_safe_float(getattr(self.cfg, "star_weight_actr", 0.08), 0.08),
            constant_bonus=_safe_float(getattr(self.cfg, "star_constant_bonus", 0.08), 0.08),
            novelty_bonus=_safe_float(getattr(self.cfg, "star_novelty_bonus", 0.04), 0.04),
            ignored_penalty=_safe_float(getattr(self.cfg, "star_ignored_penalty", 0.18), 0.18),
        )

    def _embedding_client(self) -> Optional[EmbeddingClient]:
        star_enabled = bool(getattr(self.cfg, "enable_star_embeddings", getattr(self.cfg, "enable_recall_embeddings", False)))
        if not star_enabled:
            return None
        client = EmbeddingClient(
            base_url=getattr(self.cfg, "embedding_base_url", ""),
            api_key=getattr(self.cfg, "embedding_api_key", ""),
            model=getattr(self.cfg, "embedding_model", ""),
            expected_dim=int(getattr(self.cfg, "embedding_dim", 1024) or 1024),
        )
        return client if client.enabled else None

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

    async def process_inline_stars(
        self,
        session: dict,
        inline_stars: list[Any],
        assistant_text: str,
        source_model: str,
    ) -> dict[str, Any]:
        if not getattr(self.cfg, "enable_inline_star_capture", True):
            return {"ok": False, "reason": "inline star capture disabled."}
        if not self.supabase:
            return {"ok": False, "reason": "Supabase is not configured."}
        stars = [item for item in inline_stars if self._inline_star_content(item)]
        if not stars:
            return {"ok": False, "reason": "no inline stars."}

        inserted: list[str | None] = []
        discarded = 0
        for item in stars[:4]:
            result = await self.create_star(
                content=item,
                session_tag=session.get("session_tag") or "default",
                source_model=f"inline-star:{source_model}",
                source_session_id=session.get("id"),
                source_excerpt=_shorten(assistant_text, 1200),
            )
            if result.get("ok"):
                inserted.append(result.get("star_id"))
            else:
                discarded += 1
        return {
            "ok": True,
            "inline_count": len(stars),
            "inserted_count": len([item for item in inserted if item]),
            "discarded_count": discarded,
        }

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

    async def review(
        self,
        *,
        limit_new: Optional[int] = None,
        candidates_per_star: Optional[int] = None,
        total_candidate_limit: Optional[int] = None,
        session_tag: Optional[str] = None,
        review_scope: str = "shenyu",
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        new_limit = _safe_int(limit_new if limit_new is not None else getattr(self.cfg, "star_review_new_limit", 4), 4, 1, 10)
        per_star = _safe_int(
            candidates_per_star if candidates_per_star is not None else getattr(self.cfg, "star_review_candidates_per_star", 2),
            2,
            1,
            5,
        )
        total_limit = _safe_int(
            total_candidate_limit if total_candidate_limit is not None else getattr(self.cfg, "star_review_total_candidate_limit", 8),
            8,
            1,
            30,
        )
        scope = (review_scope or "shenyu").strip().lower()
        is_admin_review = scope in {"admin", "frontend", "yuan", "yuanyuan", "圆圆", "圆儿"}
        query_limit = new_limit if not is_admin_review else max(new_limit * 8, 40)
        params: dict[str, str] = {
            "select": STAR_SELECT,
            "status": "eq.active",
            "order": "created_at.asc",
            "limit": str(query_limit),
        }
        if not is_admin_review:
            params["reviewed_at"] = "is.null"
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        seeds = await self.supabase.query(STAR_TABLE, params)
        if is_admin_review:
            seeds = [
                seed
                for seed in seeds
                if not self._admin_reviewed(seed)
            ][:new_limit]
        items: list[dict[str, Any]] = []
        remaining = total_limit
        reviewed_ids: list[str] = []
        for seed in seeds:
            seed_id = _node_id(seed.get("id"))
            excluded_candidate_ids = await self._admin_scored_candidate_ids(seed_id) if is_admin_review else set()
            if remaining > 0:
                per_seed_limit = min(per_star, remaining)
                ranked = await self._rank_for_seed(
                    seed,
                    surface="admin_review" if is_admin_review else "review",
                    session_tag=session_tag or seed.get("session_tag"),
                    limit=per_seed_limit,
                    shown=True,
                    exclude_node_ids=excluded_candidate_ids,
                )
            else:
                ranked = {"run_id": None, "items": []}
            if is_admin_review and excluded_candidate_ids and not ranked.get("items"):
                await self._mark_admin_reviewed(seed_id, run_id=ranked.get("run_id"), scored_by="圆圆")
                continue
            items.append(
                {
                    "star": self._public_star(seed),
                    "run_id": ranked.get("run_id"),
                    "candidates": ranked.get("items") or [],
                }
            )
            remaining -= len(ranked.get("items") or [])
            if seed_id:
                reviewed_ids.append(seed_id)
        if reviewed_ids and not is_admin_review:
            now_text = iso_now()
            for star_id in reviewed_ids:
                try:
                    await self.supabase.update(STAR_TABLE, {"id": star_id}, {"reviewed_at": now_text})
                except Exception as exc:
                    logger.warning("[Star] Failed to mark reviewed: id=%s error=%s", star_id, exc)
        return {
            "ok": True,
            "count": len(items),
            "new_star_limit": new_limit,
            "candidates_per_star": per_star,
            "total_candidate_limit": total_limit,
            "review_scope": "admin" if is_admin_review else "shenyu",
            "items": items,
        }

    def _admin_reviewed(self, row: dict[str, Any]) -> bool:
        metadata = _json_dict(row.get("metadata"))
        admin_review = _json_dict(metadata.get("admin_review"))
        return bool(metadata.get("admin_reviewed_at") or admin_review.get("completed_at"))

    def _is_admin_feedback(self, scored_by: str, metadata: Optional[dict[str, Any]]) -> bool:
        scorer = (scored_by or "").strip()
        meta = _json_dict(metadata)
        surface = str(meta.get("surface") or "").strip().lower()
        return scorer in ADMIN_SCORERS or surface.startswith("admin")

    async def _admin_scored_candidate_ids(self, seed_id: str) -> set[str]:
        if not seed_id:
            return set()
        try:
            runs = await self.supabase.query(
                STAR_RUN_TABLE,
                {
                    "select": "id,seed_node_id,surface,created_at",
                    "seed_node_type": "eq.star",
                    "seed_node_id": f"eq.{seed_id}",
                    "order": "created_at.desc",
                    "limit": "80",
                },
            )
        except Exception as exc:
            logger.warning("[Star] Failed to load admin review history: seed=%s error=%s", seed_id, exc)
            return set()
        run_ids = [_node_id(row.get("id")) for row in runs if row.get("id")]
        if not run_ids:
            return set()
        try:
            feedback_rows = await self.supabase.query(
                STAR_FEEDBACK_TABLE,
                {
                    "select": "run_id,candidate_node_id,scored_by,metadata",
                    "run_id": "in.(" + ",".join(run_ids) + ")",
                    "limit": "500",
                },
            )
        except Exception as exc:
            logger.warning("[Star] Failed to load admin candidate feedback: seed=%s error=%s", seed_id, exc)
            return set()
        return {
            _node_id(row.get("candidate_node_id"))
            for row in feedback_rows
            if row.get("candidate_node_id") and self._is_admin_feedback(row.get("scored_by") or "", row.get("metadata"))
        }

    async def _maybe_mark_admin_reviewed(
        self,
        *,
        run_id: Optional[str],
        scored_by: str,
        feedback: str,
    ) -> None:
        if not run_id:
            return
        run_rows = await self.supabase.query(
            STAR_RUN_TABLE,
            {"select": "id,seed_node_id,seed_node_type,surface", "id": f"eq.{run_id}", "limit": "1"},
        )
        run = run_rows[0] if run_rows else None
        seed_id = _node_id((run or {}).get("seed_node_id"))
        if not run or (run.get("seed_node_type") or "star") != "star" or not seed_id:
            return
        candidate_rows = await self.supabase.query(
            STAR_CANDIDATE_TABLE,
            {
                "select": "id,shown,action_status",
                "run_id": f"eq.{run_id}",
                "shown": "eq.true",
                "limit": "100",
            },
        )
        shown_candidates = [row for row in candidate_rows if bool(row.get("shown"))]
        if shown_candidates and any(not (row.get("action_status") or "").strip() for row in shown_candidates):
            return
        if not shown_candidates and feedback != "missed":
            return
        await self._mark_admin_reviewed(seed_id, run_id=run_id, scored_by=scored_by)

    async def _mark_admin_reviewed(self, seed_id: str, *, run_id: Optional[str], scored_by: str) -> None:
        if not seed_id:
            return
        rows = await self.supabase.query(
            STAR_TABLE,
            {"select": "id,metadata", "id": f"eq.{seed_id}", "limit": "1"},
        )
        if not rows:
            return
        metadata = _json_dict(rows[0].get("metadata"))
        now_text = iso_now()
        admin_review = _json_dict(metadata.get("admin_review"))
        admin_review.update(
            {
                "completed_at": now_text,
                "run_id": run_id,
                "scored_by": (scored_by or "圆圆").strip() or "圆圆",
            }
        )
        metadata["admin_review"] = admin_review
        metadata["admin_reviewed_at"] = now_text
        await self.supabase.update(STAR_TABLE, {"id": seed_id}, {"metadata": metadata})

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
        default_feedback = str(feedback).strip().lower() if isinstance(feedback, str) else ""
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

            feedback_key = str(raw_dict.get("feedback") or default_feedback or "").strip().lower()
            if feedback_key not in FEEDBACK_VALUES:
                return [], f"feedback[{index}] must be one of {sorted(FEEDBACK_VALUES)}."

            item_metadata = _json_dict(default_metadata)
            item_metadata.update(_json_dict(raw_dict.get("metadata")))
            item_run_id = _node_id(raw_dict.get("run_id")) or default_run_id or None
            item_candidate_id = _node_id(raw_dict.get("candidate_id")) or default_candidate_id or None
            item_candidate_node_id = (
                _node_id(raw_dict.get("candidate_star_id"))
                or _node_id(raw_dict.get("candidate_node_id"))
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
                    "note": str(raw_dict.get("note") or default_note).strip(),
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

    async def mark_constant(self, star_id: str, is_constant: bool = True) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        star_id = _node_id(star_id)
        if not star_id:
            return {"ok": False, "error": "star_id is required."}
        rows = await self.supabase.update(STAR_TABLE, {"id": star_id}, {"is_constant": bool(is_constant)})
        return {"ok": True, "star_id": star_id, "updated": rows}

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
        trace_log: Optional[dict] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "error": "Supabase is not configured."}
        clean_query = (query or "").strip()
        if not clean_query:
            return {"ok": True, "query": clean_query, "count": 0, "items": []}
        _mark_request_log_phase(
            trace_log,
            "stars.rank_start",
            detail={"surface": surface, "query_chars": len(clean_query), "limit": limit},
        )
        rows, query_embedding_status = await self._candidate_rows(clean_query, trace_log=trace_log)
        _mark_request_log_phase(
            trace_log,
            "stars.candidates_done",
            detail={"rows": len(rows), "query_embedding_status": query_embedding_status},
        )
        if not rows:
            return {"ok": True, "query": clean_query, "count": 0, "items": []}
        scored = await self._score_rows(query=clean_query, rows=rows, seed=None, surface=surface, trace_log=trace_log)
        _mark_request_log_phase(trace_log, "stars.score_done", detail={"scored": len(scored)})
        selected = self._select_for_surface(scored, limit=max(1, min(int(limit or 3), 30)), surface=surface)
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
        return {"ok": True, "query": clean_query, "count": len(items), "items": items, "run_id": run_id}

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
        rows, query_embedding_status = await self._candidate_rows(seed.get("content") or "")
        seed_id = _node_id(seed.get("id"))
        excluded = {_node_id(item) for item in (exclude_node_ids or set()) if _node_id(item)}
        rows = [row for row in rows if _node_id(row.get("id")) != seed_id and _node_id(row.get("id")) not in excluded]
        scored = await self._score_rows(query=seed.get("content") or "", rows=rows, seed=seed, surface=surface)
        selected = self._select_for_surface(scored, limit=max(1, min(int(limit or 3), 10)), surface=surface)
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
        trace_log: Optional[dict] = None,
    ) -> tuple[list[dict[str, Any]], str]:
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
        return list(rows_by_id.values()), embedding_status

    def _select_for_surface(self, scored: list[dict[str, Any]], *, limit: int, surface: str) -> list[dict[str, Any]]:
        if surface == "chat_inject":
            return self._select_for_chat_inject(scored, limit=limit)
        return self._select_for_review(scored, limit=limit)

    def _select_for_chat_inject(self, scored: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        min_score = self._min_score()
        related_min = self._related_min_score()
        selected: list[dict[str, Any]] = [
            item
            for item in scored
            if float(item.get("final_score") or 0.0) >= min_score
            and float((item.get("features") or {}).get("related_signal") or 0.0) >= related_min
        ]
        if not selected:
            fallback_limit = _safe_int(getattr(self.cfg, "star_chat_explicit_fallback_limit", 1), 1, 0, 3)
            if fallback_limit > 0:
                selected = [
                    item
                    for item in scored
                    if bool((item.get("features") or {}).get("explicit_mention"))
                ][: min(limit, fallback_limit)]
        return selected[:limit]

    def _select_for_review(self, scored: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        return scored[:limit]

    async def _vector_rows(self, query: str, *, trace_log: Optional[dict] = None) -> list[dict[str, Any]]:
        client = self._embedding_client()
        if not client or not query.strip() or not hasattr(self.supabase, "rpc"):
            _mark_request_log_phase(
                trace_log,
                "stars.vector_skipped",
                detail={
                    "embedding_client": bool(client),
                    "has_query": bool(query.strip()),
                    "has_rpc": hasattr(self.supabase, "rpc"),
                },
            )
            return []
        _mark_request_log_phase(
            trace_log,
            "stars.embedding_start",
            detail={"model": client.model, "query_chars": min(len(query), 1600)},
        )
        vector, error = await client.embed(query[:1600])
        if error or vector is None:
            _mark_request_log_phase(
                trace_log,
                "stars.embedding_failed",
                detail={"error": _shorten(error or "embedding failed", 240)},
            )
            return []
        _mark_request_log_phase(trace_log, "stars.embedding_done", detail={"dimensions": len(vector)})
        try:
            _mark_request_log_phase(
                trace_log,
                "stars.vector_rpc_start",
                detail={"match_count": min(self._candidate_limit(), 120)},
            )
            rows = await self.supabase.rpc(
                "match_shenyu_stars",
                {
                    "query_embedding": _vector_literal(vector),
                    "match_count": min(self._candidate_limit(), 120),
                    "include_status": "active",
                },
            )
        except Exception as exc:
            logger.warning("[Star] vector search failed: %s", exc)
            _mark_request_log_phase(
                trace_log,
                "stars.vector_rpc_failed",
                detail={"error": _shorten(str(exc), 240)},
            )
            return []
        _mark_request_log_phase(
            trace_log,
            "stars.vector_rpc_done",
            detail={"rows": len(rows) if isinstance(rows, list) else 0},
        )
        return rows if isinstance(rows, list) else []

    async def _score_rows(
        self,
        *,
        query: str,
        rows: list[dict[str, Any]],
        seed: Optional[dict[str, Any]],
        surface: str = "",
        trace_log: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        star_ids = [_node_id(row.get("id")) for row in rows if row.get("id")]
        _mark_request_log_phase(trace_log, "stars.activity_features_start", detail={"star_ids": len(star_ids)})
        actr_scores, ignored_penalties, recent_fatigue = await self._activity_features(
            star_ids,
            include_recent_fatigue=surface == "chat_inject",
            trace_log=trace_log,
        )
        _mark_request_log_phase(
            trace_log,
            "stars.activity_features_done",
            detail={
                "actr": len(actr_scores),
                "ignored": len(ignored_penalties),
                "recent_fatigue": len(recent_fatigue),
            },
        )
        seed_chord = seed or _extract_chord_from_query(query)
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
            base_items.append(
                {
                    "row": row,
                    "keyword_hits": hits,
                    "base_score": base_score,
                    "features": {
                        "content_score": _clamp(content_score),
                        "keyword_score": _clamp(keyword_score),
                        "chord_score": _clamp(chord_score),
                        "harmony_score": 0.0,
                        "content_gravity_score": _clamp(content_gravity),
                        "actr_score": actr_scores.get(star_id, 0.0),
                        "constant_bonus": 1.0 if row.get("is_constant") else 0.0,
                        "novelty_bonus": 0.0 if row.get("activation_count") else 1.0,
                        "ignored_penalty": ignored_penalties.get(star_id, 0.0),
                        "recent_fatigue_penalty": recent_fatigue.get(star_id, 0.0),
                    },
                }
            )
        anchors = self._anchor_ids(base_items, seed)
        _mark_request_log_phase(trace_log, "stars.harmony_start", detail={"anchors": len(anchors)})
        harmony_scores = await self._harmony_scores(anchors, trace_log=trace_log)
        _mark_request_log_phase(trace_log, "stars.harmony_done", detail={"scores": len(harmony_scores)})
        weights = self._weights()
        scored: list[dict[str, Any]] = []
        for item in base_items:
            star_id = _node_id(item["row"].get("id"))
            features = dict(item["features"])
            features["harmony_score"] = max(features["harmony_score"], harmony_scores.get(star_id, 0.0))
            related_signal = max(
                features["content_score"],
                features["keyword_score"],
                features["chord_score"],
                features["harmony_score"],
            )
            features["related_signal"] = related_signal
            explicit_hits = [hit for hit in item.get("keyword_hits") or [] if _significant_hit(hit)]
            features["explicit_mention"] = 1.0 if explicit_hits else 0.0
            item["explicit_hits"] = explicit_hits
            if related_signal <= 0:
                continue
            final = (
                features["content_score"] * weights.content
                + features["keyword_score"] * weights.keyword
                + features["harmony_score"] * weights.harmony
                + features["chord_score"] * weights.chord
                + features["actr_score"] * weights.actr
                + features["constant_bonus"] * weights.constant_bonus
                + features["novelty_bonus"] * weights.novelty_bonus
                - features["ignored_penalty"] * weights.ignored_penalty
                - features["recent_fatigue_penalty"]
            )
            if final <= 0 and not seed:
                continue
            item["final_score"] = max(0.0, final)
            item["features"] = features
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
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        if not star_ids:
            return {}, {}, {}
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
        ignored_penalties = await self._ignored_penalties(star_ids)
        _mark_request_log_phase(trace_log, "stars.ignored_penalties_done", detail={"scores": len(ignored_penalties)})
        return actr_scores, ignored_penalties, recent_fatigue

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

    async def _ignored_penalties(self, star_ids: list[str]) -> dict[str, float]:
        try:
            rows = await self.supabase.query(
                STAR_CANDIDATE_TABLE,
                {
                    "select": "candidate_node_id,shown,action_status,created_at",
                    "candidate_node_type": "eq.star",
                    "candidate_node_id": "in.(" + ",".join(star_ids) + ")",
                    "shown": "eq.true",
                    "order": "created_at.desc",
                    "limit": str(min(max(len(star_ids) * 6, 100), 3000)),
                },
            )
        except Exception:
            return {}
        by_star: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_star.setdefault(_node_id(row.get("candidate_node_id")), []).append(row)
        penalties: dict[str, float] = {}
        for star_id, history in by_star.items():
            latest = history[:3]
            if len(latest) < 3:
                continue
            actions = [(row.get("action_status") or "").strip().lower() for row in latest]
            if any(action in POSITIVE_FEEDBACK for action in actions):
                continue
            if all(action in {"", "skipped", "negative"} for action in actions):
                penalties[star_id] = 1.0
        return penalties

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
                        "keyword_hits": item.get("keyword_hits") or [],
                        "explicit_hits": item.get("explicit_hits") or [],
                        "related_signal": features.get("related_signal") or 0.0,
                        "explicit_mention": features.get("explicit_mention") or 0.0,
                        "recent_fatigue_penalty": features.get("recent_fatigue_penalty") or 0.0,
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

    async def _attach_embedding(self, payload: dict[str, Any], chord: str, content: str) -> None:
        client = self._embedding_client()
        if not client:
            payload["embedding_status"] = "skipped"
            return
        text = "\n".join(part for part in [chord, content] if part).strip()[:1600]
        if not text:
            payload["embedding_status"] = "skipped"
            return
        vector, error = await client.embed(text)
        if error or vector is None:
            payload["embedding_status"] = "failed"
            payload["embedding_error"] = error or "embedding failed"
            return
        payload["embedding"] = _vector_literal(vector)
        payload["embedding_model"] = client.model
        payload["embedding_status"] = "ready"
        payload["embedding_error"] = None
        payload["embedded_at"] = iso_now()

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

    def _inline_star_content(self, star: Any) -> str:
        parsed = parse_star_payload(star)
        content = (parsed.get("content") or "").strip()
        if not content:
            return ""
        if not re.sub(r"[\W_]+", "", content, flags=re.UNICODE):
            return ""
        return content

    def _public_star(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata = _json_dict(row.get("metadata"))
        chord_sequence = metadata.get("chord_sequence")
        if not isinstance(chord_sequence, list):
            chord_sequence = []
        chord_sequence = [part for part in (_node_id(item) for item in chord_sequence) if part]
        if not chord_sequence:
            parsed_sequence = _split_chord_sequence(row.get("chord"))
            if len(parsed_sequence) > 1:
                chord_sequence = parsed_sequence
        return {
            "id": row.get("id"),
            "session_tag": row.get("session_tag"),
            "content": row.get("content") or "",
            "chord": row.get("chord") or "",
            "chord_sequence": chord_sequence,
            "chord_root": row.get("chord_root") or "",
            "chord_quality": row.get("chord_quality") or "",
            "status": row.get("status") or "active",
            "is_constant": bool(row.get("is_constant")),
            "reviewed_at": row.get("reviewed_at"),
            "activation_count": row.get("activation_count") or 0,
            "last_activated_at": row.get("last_activated_at"),
            "source_model": row.get("source_model") or "",
            "source_session_id": row.get("source_session_id"),
            "source_excerpt": row.get("source_excerpt") or "",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _public_candidate(self, item: dict[str, Any], *, run_id: Optional[str]) -> dict[str, Any]:
        row = item.get("row") or {}
        features = item.get("features") or {}
        star = self._public_star(row)
        return {
            **star,
            "run_id": run_id,
            "candidate_id": item.get("candidate_id"),
            "score": round(float(item.get("final_score") or 0.0), 4),
            "scores": {key: round(float(value or 0.0), 4) for key, value in features.items()},
            "keyword_hits": item.get("keyword_hits") or [],
        }


def render_star_context(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = []
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        chord = (item.get("chord") or "").strip()
        prefix = f"{chord} · " if chord else ""
        lines.append(f"- {prefix}{_shorten(content, 220)}")
    return "\n".join(lines)
