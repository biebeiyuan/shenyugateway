from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from ..runtime import iso_now, logger
from ._helpers import (
    _feedback_value, _json_dict, _node_id,
    STAR_CANDIDATE_TABLE, STAR_FEEDBACK_TABLE, STAR_RUN_TABLE, STAR_TABLE,
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
        constellation_name: str = "",
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
            constellation_name=constellation_name,
            scored_by=scored_by,
            note=note,
            metadata=metadata,
        )
        if error:
            return {"ok": False, "error": error}

        rows = []
        connected_edges = 0
        for payload in payloads:
            row = await self._feedback_one(payload)
            rows.append(row)
            # 用落库后那一行来建边，不用原始 payload：`_feedback_one` 会从候选行
            # 补出 candidate_node_id 和 run_id，而他只给候选序号时 payload 里
            # 这两个都是空的。读回执而不是读入参，是这里唯一能拿到全的地方。
            resolved = dict(payload)
            if isinstance(row, dict):
                for key in ("run_id", "candidate_node_id"):
                    if row.get(key):
                        resolved[key] = row[key]
            # 「连起来」以前只往反馈表记一行，`shenyu_star_links` 一条边都不建：
            # 他说过 12 次连起来，库里 0 条边，那 12 个洞察全留在 note 的文字里
            # 没有生效。connect_constellation 走的是同一张表、同一个
            # relation_type，只是 review 这条路没接上。
            if _feedback_value(payload.get("feedback")) == "connected":
                connected_edges += await self._link_from_feedback(resolved)

        out: dict[str, Any] = {
            "ok": True,
            "count": len(rows),
            "feedback": rows[0] if len(rows) == 1 else rows,
        }
        if connected_edges:
            out["edge_count"] = connected_edges
        return out

    async def _link_from_feedback(self, payload: dict[str, Any]) -> int:
        """把一条「连起来」变成 `shenyu_star_links` 里真的边。

        连的是「种子星 ↔ 这个候选」：review 是拿一颗星去找相关的，所以说
        「连起来」的意思就是这两颗是一回事。种子星从 run 表的 `seed_node_id`
        查——候选行自己只知道它是谁，不知道它是为谁被找出来的。

        建不了边不让整条反馈失败：反馈已经记下了，边只是这次没连上。
        """
        candidate_node_id = _node_id(payload.get("candidate_node_id"))
        run_id = _node_id(payload.get("run_id"))
        if not candidate_node_id or not run_id:
            return 0
        try:
            runs = await self.supabase.query(
                STAR_RUN_TABLE,
                {"select": "seed_node_id,seed_node_type", "id": f"eq.{run_id}", "limit": "1"},
            )
        except Exception as exc:
            logger.warning("[Star] connected 反馈查种子星失败: run_id=%s error=%s", run_id, exc)
            return 0
        seed_row = runs[0] if runs else None
        if not isinstance(seed_row, dict):
            return 0
        seed_id = _node_id(seed_row.get("seed_node_id"))
        if not seed_id or seed_id == candidate_node_id:
            return 0
        if _node_id(seed_row.get("seed_node_type") or "star") != "star":
            return 0
        # 星座名：他说「连起来」时可以顺手给这条线起名。走 connect_constellation
        # 同一个 metadata 形状，所以 Admin 星图和 harmony 通道照旧认得。
        metadata = _json_dict(payload.get("metadata"))
        name = str(
            _first_nonempty(payload, "constellation_name", "star_name") or "",
        ).strip()
        result = await self.connect_constellation(
            [seed_id, candidate_node_id],
            name=name,
            relation_type="constellation",
            scored_by=str(payload.get("scored_by") or "沈予").strip() or "沈予",
            note=str(payload.get("note") or "").strip(),
        )
        if not isinstance(result, dict) or not result.get("ok"):
            logger.warning(
                "[Star] connected 反馈没能建边: seed=%s candidate=%s error=%s",
                seed_id,
                candidate_node_id,
                (result or {}).get("error"),
            )
            return 0
        return int(result.get("edge_count") or 0)

    def _feedback_payloads(
        self,
        *,
        feedback: Any,
        items: Any,
        run_id: Optional[str],
        candidate_id: Optional[str],
        candidate_star_id: Optional[str],
        expected_star_id: Optional[str],
        constellation_name: str,
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
        default_constellation_name = (constellation_name or "").strip()

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
                    # 「连起来」时顺手给这条线起的名字。星星聚起来就是星座，
                    # 名字正是"这几颗为什么是一回事"的答案——没有名字的线，
                    # 以后带出来也说不清为什么。
                    "constellation_name": str(
                        _first_nonempty(raw_dict, "constellation_name", "star_name")
                        or default_constellation_name
                        or ""
                    ).strip(),
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
