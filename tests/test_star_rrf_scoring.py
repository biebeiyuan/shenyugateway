from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

from shenyu_gateway.stars import StarService
from shenyu_gateway.stars._helpers import _direct_reference_kinds


class FakeSupabase:
    """Fake with the star tables empty except shenyu_stars (seeded per test).

    Empty activation/feedback/link tables => _activity_features returns all-zero
    (actr=0, no fatigue, no negative), so _score_rows exercises the RRF + modifier
    math against controllable inputs.
    """

    def __init__(self):
        self.tables = {
            "shenyu_stars": [],
            "shenyu_star_recall_runs": [],
            "shenyu_star_recall_candidates": [],
            "shenyu_star_feedback": [],
            "shenyu_star_activations": [],
            "shenyu_star_links": [],
        }

    async def query(self, table, params=None):
        params = dict(params or {})
        rows = [dict(row) for row in self.tables.get(table, [])]
        for key, value in params.items():
            if key in {"select", "order", "limit"}:
                continue
            if value == "is.null":
                rows = [r for r in rows if r.get(key) is None]
            elif value == "not.is.null":
                rows = [r for r in rows if r.get(key) is not None]
            elif isinstance(value, str) and value.startswith("eq."):
                expected = value[3:]
                if expected in {"true", "false"}:
                    rows = [r for r in rows if bool(r.get(key)) is (expected == "true")]
                else:
                    rows = [r for r in rows if str(r.get(key)) == expected]
            elif isinstance(value, str) and value.startswith("in.(") and value.endswith(")"):
                expected = set(value[4:-1].split(","))
                rows = [r for r in rows if str(r.get(key)) in expected]
        limit = int(params.get("limit") or len(rows) or 0)
        return rows[:limit]


def _cfg():
    return SimpleNamespace(
        enable_star_embeddings=False,
        star_candidate_limit=50,
        star_min_score=0.008,
        star_related_min_score=0.22,
        star_recent_fatigue_hours=6,
        star_recent_fatigue_penalty=0.14,
        star_rrf_ch_content=1.0,
        star_rrf_ch_keyword=0.8,
        star_rrf_ch_chord=0.6,
        star_rrf_ch_harmony=0.7,
        star_rrf_ch_scene=0.4,
        star_rrf_ch_explicit=0.5,
        star_rrf_k=60,
        star_rrf_actr_floor=0.5,
        star_rrf_constant_boost=1.3,
        star_rrf_date_boost_max=0.3,
    )


def _star(star_id, content, *, is_constant=False, activation_count=0):
    return {
        "id": star_id,
        "content": content,
        "chord": "",
        "status": "active",
        "is_constant": is_constant,
        "activation_count": activation_count,
        "metadata": {},
        "created_at": "2026-06-18T00:00:00+00:00",
        "updated_at": "2026-06-18T00:00:00+00:00",
    }


def _score(rows, query="沈予 星星 房间"):
    service = StarService(_cfg(), FakeSupabase())
    return asyncio.run(service._score_rows(query=query, rows=rows, seed=None, surface="chat_inject"))


def _by_id(scored):
    return {s["row"]["id"]: s for s in scored}


def test_higher_content_overlap_ranks_first():
    # star-1 shares more tokens with the query than star-2.
    rows = [
        _star("star-1", "沈予 星星 房间 一起"),
        _star("star-2", "无关 内容 随便"),
    ]
    scored = _score(rows)
    assert scored, "expected at least one eligible star"
    # star-1 must outrank star-2 (or star-2 filtered out for zero signal).
    ids = [s["row"]["id"] for s in scored]
    assert ids[0] == "star-1"


def test_rrf_denominator_uses_k_plus_rank_plus_one():
    # A single star that hits only the content channel (weight 1.0), rank_0 = 0,
    # k = 60 => content contribution = 1.0 / (60 + 0 + 1) = 1/61.
    rows = [_star("solo", "沈予 星星 房间")]
    scored = _score(rows)
    solo = _by_id(scored)["solo"]
    contribs = solo["features"]["rrf_contributions"]
    # content channel present and equals 1/61
    assert abs(contribs.get("content_score", 0.0) - (1.0 / 61.0)) < 1e-9


def test_modifier_chain_is_multiplicative_not_additive():
    # With zero activations: actr_mod = floor = 0.5, novelty_mod = 1/(1+log10(1)) = 1.0,
    # constant_mod = 1.0, fatigue_mod = 1.0, date_mod = 1.0.
    # So final should equal rrf_score * 0.5, NOT rrf_score + 0.5.
    rows = [_star("solo", "沈予 星星 房间")]
    scored = _score(rows)
    solo = _by_id(scored)["solo"]
    rrf = solo["features"]["rrf_score"]
    final = solo["final_score"]
    assert solo["features"]["actr_modifier"] == 0.5
    assert abs(solo["features"]["novelty_modifier"] - 1.0) < 1e-9
    assert abs(final - rrf * 0.5) < 1e-9  # multiplicative
    assert abs(final - (rrf + 0.5)) > 1e-6  # definitely not additive


def test_constant_star_gets_constant_boost():
    rows = [_star("c", "沈予 星星 房间", is_constant=True)]
    scored = _score(rows)
    c = _by_id(scored)["c"]
    assert c["features"]["constant_modifier"] == 1.3


def test_novelty_modifier_shrinks_with_activation_count():
    # activation_count = 9 => novelty = 1/(1+log10(10)) = 1/2 = 0.5
    rows = [_star("old", "沈予 星星 房间", activation_count=9)]
    scored = _score(rows)
    old = _by_id(scored)["old"]
    assert abs(old["features"]["novelty_modifier"] - 0.5) < 1e-9


def test_direct_reference_detector_distinguishes_hard_and_soft_matches():
    rows = [
        _star("11111111-1111-4111-8111-111111111111", "那只叫豆包的橘猫第一次跳上窗台"),
        _star("22222222-2222-4222-8222-222222222222", "一起在旧影院看完降临以后没有说话"),
    ]

    assert _direct_reference_kinds(rows[0]["id"], rows) == {rows[0]["id"]: "star_id"}
    assert _direct_reference_kinds("“旧影院看完降临”那颗星", rows) == {
        rows[1]["id"]: "exact_phrase"
    }
    assert _direct_reference_kinds("你还记得豆包吗？", rows) == {
        rows[0]["id"]: "recall_unique"
    }
    assert _direct_reference_kinds("今天晚上吃什么？", rows) == {}


def test_soft_direct_reference_requires_one_unambiguous_star():
    rows = [
        _star("star-a", "豆包第一次跳上窗台"),
        _star("star-b", "豆包后来躲进了纸箱"),
    ]

    assert _direct_reference_kinds("你还记得豆包吗？", rows) == {}


def test_low_scoring_direct_candidate_stays_in_final_proposal_then_uses_score_order():
    service = StarService(_cfg(), FakeSupabase())
    scored = [
        {"row": {"id": "high"}, "final_score": 0.03, "features": {"related_signal": 0.8}},
        {"row": {"id": "mid"}, "final_score": 0.02, "features": {"related_signal": 0.7}},
        {
            "row": {"id": "direct"},
            "final_score": 0.001,
            "features": {"related_signal": 1.0},
            "direct_reference_kind": "star_id",
        },
        {"row": {"id": "other"}, "final_score": 0.015, "features": {"related_signal": 0.6}},
    ]

    selected = asyncio.run(service._select_for_chat_inject(scored, limit=3))

    assert [item["row"]["id"] for item in selected] == ["high", "mid", "direct"]
