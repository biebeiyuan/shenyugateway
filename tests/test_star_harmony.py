from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.stars import StarService


class LinkFakeSupabase:
    """Minimal fake backing only shenyu_star_links for _harmony_scores tests.

    Supports the query filters _harmony_scores uses: eq.<val>, in.(...).
    """

    def __init__(self, links: list[dict]):
        self.tables = {"shenyu_star_links": [dict(r) for r in links]}

    async def query(self, table, params=None):
        params = dict(params or {})
        rows = [dict(row) for row in self.tables.get(table, [])]
        for key, value in params.items():
            if key in {"select", "order", "limit"}:
                continue
            if isinstance(value, str) and value.startswith("eq."):
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
    return SimpleNamespace(enable_star_embeddings=False)


def _link(frm, to, *, relation="constellation", confidence=1.0, weight=1.0, bidirectional=False):
    return {
        "from_node_id": frm,
        "to_node_id": to,
        "from_node_type": "star",
        "to_node_type": "star",
        "relation_type": relation,
        "confidence": confidence,
        "weight": weight,
        "bidirectional": bidirectional,
        "status": "active",
    }


def _harmony(links, anchor_ids):
    service = StarService(_cfg(), LinkFakeSupabase(links))
    return asyncio.run(service._harmony_scores(anchor_ids))


def test_forward_constellation_edge_scores_even_when_not_bidirectional():
    # anchor A --constellation--> B, one-directional. Forward edges always score.
    scores = _harmony([_link("A", "B", bidirectional=False)], ["A"])
    assert scores.get("B") == 1.0  # confidence 1.0 * weight 1.0 * bonus 1.0


def test_reverse_edge_scores_only_when_bidirectional():
    # Edge stored as X --> A. Anchor is A (the 'to' side).
    # Non-bidirectional reverse link must NOT be pulled.
    scores_one_way = _harmony([_link("X", "A", bidirectional=False)], ["A"])
    assert "X" not in scores_one_way

    # Bidirectional reverse link IS pulled.
    scores_two_way = _harmony([_link("X", "A", bidirectional=True)], ["A"])
    assert scores_two_way.get("X") == 1.0


def test_non_constellation_relation_uses_075_bonus():
    scores = _harmony([_link("A", "B", relation="harmony")], ["A"])
    assert abs(scores.get("B", 0.0) - 0.75) < 1e-9  # 1.0 * 1.0 * 0.75


def test_confidence_and_weight_multiply_through():
    scores = _harmony([_link("A", "B", relation="harmony", confidence=0.5, weight=0.8)], ["A"])
    # 0.5 * 0.8 * 0.75 = 0.30
    assert abs(scores.get("B", 0.0) - 0.30) < 1e-9


def test_anchor_targets_are_dropped():
    # Both endpoints are anchors -> no external target to score.
    scores = _harmony([_link("A", "B")], ["A", "B"])
    assert scores == {}


def test_multiple_links_take_max():
    links = [
        _link("A", "B", relation="harmony", confidence=0.4, weight=1.0),  # 0.30
        _link("A", "B", relation="constellation", confidence=1.0, weight=1.0),  # 1.0
    ]
    scores = _harmony(links, ["A"])
    assert scores.get("B") == 1.0  # max of the two


def test_clamp_caps_at_one():
    scores = _harmony([_link("A", "B", confidence=2.0, weight=2.0)], ["A"])
    assert scores.get("B") == 1.0  # 2*2*1.0 clamped to 1.0


def test_empty_anchors_returns_empty():
    assert _harmony([_link("A", "B")], []) == {}
