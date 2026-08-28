from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.stars import StarService

from .fake_postgrest import project_select


class LinkFakeSupabase:
    """Fake backing shenyu_star_links for _constellation_pull tests."""

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
        return project_select(rows[:limit], params)


def _cfg():
    return SimpleNamespace(enable_star_embeddings=False)


def _link(frm, to, *, relation="constellation", bidirectional=False):
    return {
        "from_node_id": frm,
        "to_node_id": to,
        "from_node_type": "star",
        "to_node_type": "star",
        "relation_type": relation,
        "bidirectional": bidirectional,
        "status": "active",
    }


def _scored(star_id, final_score, *, explicitly_negative=False):
    return {
        "row": {"id": star_id},
        "features": {"explicitly_negative": explicitly_negative},
        "final_score": final_score,
    }


def _pull(links, anchor_ids, all_scored, exclude):
    service = StarService(_cfg(), LinkFakeSupabase(links))
    return asyncio.run(service._constellation_pull(set(anchor_ids), all_scored, set(exclude)))


def test_forward_neighbor_is_pulled():
    links = [_link("A", "B")]
    scored = [_scored("B", 0.5)]
    pulled = _pull(links, ["A"], scored, exclude={"A"})
    assert [p["row"]["id"] for p in pulled] == ["B"]


def test_excluded_ids_are_not_pulled():
    # B is already a primary pick (in exclude) -> must not be re-pulled.
    links = [_link("A", "B")]
    scored = [_scored("B", 0.5)]
    pulled = _pull(links, ["A"], scored, exclude={"A", "B"})
    assert pulled == []


def test_explicitly_negative_neighbor_is_excluded():
    links = [_link("A", "B")]
    scored = [_scored("B", 0.9, explicitly_negative=True)]
    pulled = _pull(links, ["A"], scored, exclude={"A"})
    assert pulled == []


def test_non_bidirectional_reverse_link_is_not_pulled():
    # Edge stored as B --> A (anchor A is the 'to' side), one-directional.
    # The reverse pull requires bidirectional=true, so B must NOT surface.
    links = [_link("B", "A", bidirectional=False)]
    scored = [_scored("B", 0.5)]
    pulled = _pull(links, ["A"], scored, exclude={"A"})
    assert pulled == []


def test_bidirectional_reverse_link_is_pulled():
    links = [_link("B", "A", bidirectional=True)]
    scored = [_scored("B", 0.5)]
    pulled = _pull(links, ["A"], scored, exclude={"A"})
    assert [p["row"]["id"] for p in pulled] == ["B"]


def test_negative_final_score_is_excluded():
    links = [_link("A", "B")]
    scored = [_scored("B", -0.1)]
    pulled = _pull(links, ["A"], scored, exclude={"A"})
    assert pulled == []


def test_pulled_neighbors_sorted_by_score_desc():
    links = [_link("A", "B"), _link("A", "C"), _link("A", "D")]
    scored = [_scored("B", 0.2), _scored("C", 0.9), _scored("D", 0.5)]
    pulled = _pull(links, ["A"], scored, exclude={"A"})
    assert [p["row"]["id"] for p in pulled] == ["C", "D", "B"]


def test_no_links_returns_empty():
    scored = [_scored("B", 0.5)]
    pulled = _pull([], ["A"], scored, exclude={"A"})
    assert pulled == []
