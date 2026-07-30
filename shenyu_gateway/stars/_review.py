from __future__ import annotations

import json
from typing import Any, Optional

from ..runtime import iso_now, logger
from ._helpers import (
    ADMIN_SCORERS, STAR_CANDIDATE_TABLE, STAR_FEEDBACK_TABLE, STAR_RUN_TABLE,
    STAR_TABLE, STAR_SELECT,
    _json_dict, _node_id, _safe_int,
)


class ReviewMixin:

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
        # Shenyu's review queue is resident-wide. The caller's session tag is
        # still recorded on review runs below, but it must not hide stars that
        # were created in another conversation.
        if session_tag and is_admin_review:
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
        remaining_unreviewed = 0
        if not is_admin_review:
            try:
                unreviewed_rows = await self.supabase.query(STAR_TABLE, {
                    "select": "id",
                    "status": "eq.active",
                    "reviewed_at": "is.null",
                    "limit": "200",
                })
                remaining_unreviewed = len(unreviewed_rows)
            except Exception:
                pass
        return {
            "ok": True,
            "count": len(items),
            "new_star_limit": new_limit,
            "candidates_per_star": per_star,
            "total_candidate_limit": total_limit,
            "review_scope": "admin" if is_admin_review else "shenyu",
            "remaining_unreviewed": remaining_unreviewed,
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
