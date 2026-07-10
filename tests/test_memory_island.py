from __future__ import annotations

from shenyu_gateway.memory_island import resolve_memory_island


def _star(
    item_id: str,
    content: str,
    *,
    explicit: float = 0.0,
    force_island_rewrite: bool = False,
) -> dict:
    return {
        "id": item_id,
        "content": content,
        "chord": "Am7",
        "scores": {"explicit_score": explicit},
        "force_island_rewrite": force_island_rewrite,
    }


def _mem(item_id: str, content: str, *, mode: str = "keyword") -> dict:
    return {
        "id": item_id,
        "content": content,
        "summary": content,
        "search_mode": mode,
    }


def test_memory_island_reuses_exact_rendered_text_when_proposal_only_reorders_items():
    initial, entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [_mem("m1", "memo")],
    )
    assert [item["id"] for item in entering["stars"]] == ["a", "b", "c"]
    original_text = initial["rendered_text"]

    retained, entering, meta = resolve_memory_island(
        initial,
        [_star("c", "third"), _star("b", "second"), _star("a", "first")],
        [_mem("m1", "memo")],
    )

    assert retained["rendered_text"] == original_text
    assert [item["id"] for item in retained["stars"]] == ["a", "b", "c"]
    assert entering == {"stars": [], "mem_notes": []}
    assert meta["decision"] == "retained"


def test_memory_island_retains_two_thirds_overlap_until_candidate_is_explicitly_forced():
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [],
    )
    retained, entering, meta = resolve_memory_island(
        initial,
        [_star("a", "first"), _star("b", "second"), _star("d", "new")],
        [],
    )
    assert [item["id"] for item in retained["stars"]] == ["a", "b", "c"]
    assert entering["stars"] == []
    assert meta["star"]["overlap"] == 0.6667

    still_retained, entering, meta = resolve_memory_island(
        initial,
        [_star("a", "first"), _star("b", "second"), _star("d", "new", explicit=1.0)],
        [],
    )
    assert [item["id"] for item in still_retained["stars"]] == ["a", "b", "c"]
    assert entering["stars"] == []
    assert meta["star"]["reason"] == "retained_overlap"

    rewritten, entering, meta = resolve_memory_island(
        initial,
        [
            _star("a", "first"),
            _star("b", "second"),
            _star("d", "new", force_island_rewrite=True),
        ],
        [],
    )
    assert [item["id"] for item in rewritten["stars"]] == ["a", "b", "d"]
    assert [item["id"] for item in entering["stars"]] == ["d"]
    assert meta["star"]["reason"] == "direct_candidate"


def test_memory_island_rewrites_when_existing_item_content_changes():
    initial, _entering, _meta = resolve_memory_island(None, [_star("a", "old")], [_mem("m1", "old memo")])
    rewritten, entering, meta = resolve_memory_island(
        initial,
        [_star("a", "new")],
        [_mem("m1", "old memo")],
    )

    assert rewritten["stars"][0]["content"] == "new"
    assert entering["stars"] == []
    assert meta["star"]["reason"] == "content_changed"
