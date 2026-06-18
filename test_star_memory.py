from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.response_capture import AssistantTagFilter, split_private_assistant_tags
from shenyu_gateway.stars import StarService, parse_star_payload


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "shenyu_stars": [],
            "shenyu_star_recall_runs": [],
            "shenyu_star_recall_candidates": [],
            "shenyu_star_feedback": [],
            "shenyu_star_activations": [],
            "shenyu_star_links": [],
        }
        self._ids = 0

    def _new_id(self, prefix):
        self._ids += 1
        return f"{prefix}-{self._ids}"

    async def query(self, table, params=None):
        params = dict(params or {})
        rows = [dict(row) for row in self.tables.get(table, [])]
        for key, value in params.items():
            if key in {"select", "order", "limit"}:
                continue
            if value == "is.null":
                rows = [row for row in rows if row.get(key) is None]
            elif value == "not.is.null":
                rows = [row for row in rows if row.get(key) is not None]
            elif isinstance(value, str) and value.startswith("eq."):
                expected = value[3:]
                rows = [row for row in rows if str(row.get(key)) == expected]
            elif isinstance(value, str) and value.startswith("in.(") and value.endswith(")"):
                expected = set(value[4:-1].split(","))
                rows = [row for row in rows if str(row.get(key)) in expected]
        limit = int(params.get("limit") or len(rows) or 0)
        return rows[:limit]

    async def insert(self, table, data):
        row = dict(data)
        row.setdefault("id", self._new_id(table))
        row.setdefault("created_at", "2026-06-18T00:00:00+00:00")
        row.setdefault("updated_at", row["created_at"])
        self.tables.setdefault(table, []).append(row)
        return dict(row)

    async def insert_many(self, table, rows):
        return [await self.insert(table, row) for row in rows]

    async def update(self, table, match, data):
        updated = []
        for row in self.tables.get(table, []):
            if all(str(row.get(key)) == str(value) for key, value in (match or {}).items()):
                row.update(data)
                updated.append(dict(row))
        return updated


def _cfg():
    return SimpleNamespace(
        enable_inline_star_capture=True,
        enable_star_embeddings=False,
        inject_stars=True,
        star_candidate_limit=50,
        star_shadow_candidate_limit=20,
        star_weight_content=0.30,
        star_weight_keyword=0.20,
        star_weight_harmony=0.35,
        star_weight_chord=0.18,
        star_weight_actr=0.08,
        star_constant_bonus=0.08,
        star_novelty_bonus=0.04,
        star_ignored_penalty=0.18,
    )


def test_star_tag_capture_and_parse_chord():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "看见了。[star chord=\"Am\"]有一点亮[/star]<heartbeat>留着</heartbeat>"
    )

    assert clean == "看见了。"
    assert heartbeat == "留着"
    assert memories == []
    assert stars == [{"content": "有一点亮", "attrs": {"chord": "Am"}}]
    assert parse_star_payload(stars[0])["chord_root"] == "A"
    assert parse_star_payload("Am · 有一点亮")["content"] == "有一点亮"


def test_streaming_star_capture_keeps_unclosed_star_visible():
    tag_filter = AssistantTagFilter()

    visible = tag_filter.feed("前面 [star]未闭合") + tag_filter.flush()

    assert visible == "前面 [star]未闭合"
    assert tag_filter.get_stars() == []


def test_review_limits_candidates_and_missed_feedback():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Am · 第一颗星")
        await service.create_star("Am · 第二颗星")
        await service.create_star("C · 第三颗星")
        result = await service.review(limit_new=2, candidates_per_star=3, total_candidate_limit=2)
        feedback = await service.feedback(
            feedback="missed",
            run_id=result["items"][0]["run_id"],
            expected_star_id="shenyu_stars-3",
            scored_by="沈予",
            note="应该反第三颗",
        )
        return result, feedback

    result, feedback = asyncio.run(run())

    assert result["ok"] is True
    assert result["count"] == 2
    assert sum(len(item["candidates"]) for item in result["items"]) <= 2
    assert feedback["ok"] is True
    assert feedback["feedback"]["feedback"] == "missed"
    assert feedback["feedback"]["expected_node_id"] == "shenyu_stars-3"


def test_star_graph_returns_links():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        first = await service.create_star("Am · 第一颗星")
        second = await service.create_star("C · 第二颗星")
        await service.connect_constellation(
            [first["star_id"], second["star_id"]],
            name="第一束光",
            scored_by="圆圆",
            note="真实连线",
        )
        return await service.graph()

    graph = asyncio.run(run())

    assert graph["ok"] is True
    assert len(graph["stars"]) == 2
    assert len(graph["links"]) == 1
    assert graph["links"][0]["name"] == "第一束光"
    assert graph["links"][0]["source"] == "shenyu_stars-1"
    assert graph["links"][0]["target"] == "shenyu_stars-2"
