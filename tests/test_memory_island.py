from __future__ import annotations

import copy

import pytest

from shenyu_gateway.memory_island import memory_island_log_content, resolve_memory_island


def _star(
    item_id: str,
    content: str,
    *,
    explicit: float = 0.0,
    force_island_rewrite: bool = False,
    direct_reference_kind: str = "",
) -> dict:
    return {
        "id": item_id,
        "content": content,
        "chord": "Am7",
        "scores": {"explicit_score": explicit},
        "force_island_rewrite": force_island_rewrite,
        "direct_reference_kind": direct_reference_kind,
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


def test_memory_island_log_content_treats_stars_and_mem_notes_symmetrically():
    previous, _entering, _meta = resolve_memory_island(
        None,
        [_star("s-old", "old star"), _star("s-update", "before")],
        [_mem("m-old", "old mem"), _mem("m-update", "before memo")],
    )
    current, _entering, _meta = resolve_memory_island(
        previous,
        [_star("s-update", "after"), _star("s-new", "new star", force_island_rewrite=True)],
        [_mem("m-update", "after memo"), _mem("m-new", "new mem", mode="entity")],
        force=True,
    )

    content = memory_island_log_content(previous, current)

    for lane_name in ("stars", "mem_notes"):
        lane = content[lane_name]
        assert lane["added_count"] == 1
        assert lane["removed_count"] == 1
        assert lane["updated_count"] == 1
        assert [item["change"] for item in lane["current"]] == ["updated", "added"]
        assert len(lane["removed"]) == 1
        assert len(lane["updated"]) == 1


def test_memory_island_log_content_bounds_display_text():
    state, _entering, _meta = resolve_memory_island(
        None,
        [_star("s-long", "s" * 400)],
        [_mem("m-long", "m" * 400)],
    )

    content = memory_island_log_content(None, state)

    assert len(content["stars"]["current"][0]["text"]) <= 220
    assert len(content["mem_notes"]["current"][0]["text"]) <= 180


def test_hard_direct_reference_bypasses_overlap_and_adopts_full_scored_order():
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [],
    )

    rewritten, entering, meta = resolve_memory_island(
        initial,
        [
            _star("b", "second"),
            _star("d", "direct", direct_reference_kind="star_id"),
            _star("a", "first"),
        ],
        [],
        advance_human_turn=True,
    )

    assert [item["id"] for item in rewritten["stars"]] == ["b", "d", "a"]
    assert [item["id"] for item in entering["stars"]] == ["d"]
    assert meta["star"]["reason"] == "direct_star_id"


def test_soft_direct_reference_is_suppressed_until_eight_real_user_turns_have_elapsed():
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [],
    )
    initial["human_turn_index"] = 10
    initial["star_soft_direct_seen_at"] = {"d": 4}
    proposal = [
        _star("a", "first"),
        _star("b", "second"),
        _star("d", "remembered", direct_reference_kind="recall_unique"),
    ]

    within_cooldown, entering, meta = resolve_memory_island(
        copy.deepcopy(initial),
        proposal,
        [],
        advance_human_turn=True,
    )
    assert [item["id"] for item in within_cooldown["stars"]] == ["a", "b", "c"]
    assert entering["stars"] == []
    assert meta["star"]["reason"] == "retained_overlap"

    initial["human_turn_index"] = 11
    after_cooldown, entering, meta = resolve_memory_island(
        initial,
        proposal,
        [],
        advance_human_turn=True,
    )
    assert [item["id"] for item in after_cooldown["stars"]] == ["a", "b", "d"]
    assert [item["id"] for item in entering["stars"]] == ["d"]
    assert after_cooldown["star_soft_direct_seen_at"]["d"] == 12
    assert meta["star"]["reason"] == "direct_recall_unique"


def test_soft_direct_reference_cooldown_accepts_runtime_override():
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [],
    )
    initial["human_turn_index"] = 5
    initial["star_soft_direct_seen_at"] = {"d": 4}

    rewritten, entering, meta = resolve_memory_island(
        initial,
        [
            _star("a", "first"),
            _star("b", "second"),
            _star("d", "remembered", direct_reference_kind="recall_unique"),
        ],
        [],
        advance_human_turn=True,
        soft_direct_cooldown_turns=2,
    )

    assert [item["id"] for item in rewritten["stars"]] == ["a", "b", "d"]
    assert [item["id"] for item in entering["stars"]] == ["d"]
    assert meta["star"]["reason"] == "direct_recall_unique"


def test_zero_soft_direct_cooldown_allows_same_turn_reentry():
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [],
    )
    initial["human_turn_index"] = 5
    initial["star_soft_direct_seen_at"] = {"d": 5}

    rewritten, _entering, meta = resolve_memory_island(
        initial,
        [
            _star("a", "first"),
            _star("b", "second"),
            _star("d", "remembered", direct_reference_kind="recall_unique"),
        ],
        [],
        soft_direct_cooldown_turns=0,
    )

    assert [item["id"] for item in rewritten["stars"]] == ["a", "b", "d"]
    assert meta["star"]["reason"] == "direct_recall_unique"


def test_inactive_current_star_forces_full_proposal():
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "archived")],
        [],
    )

    rewritten, entering, meta = resolve_memory_island(
        initial,
        [_star("b", "second"), _star("d", "new"), _star("a", "first")],
        [],
        active_star_ids={"a", "b"},
    )

    assert [item["id"] for item in rewritten["stars"]] == ["b", "d", "a"]
    assert [item["id"] for item in entering["stars"]] == ["d"]
    assert meta["star"]["reason"] == "inactive_item"


@pytest.mark.parametrize("reason", ["history_branch", "message_high_water"])
def test_external_window_force_reason_is_preserved(reason):
    initial, _entering, _meta = resolve_memory_island(
        None,
        [_star("a", "first"), _star("b", "second"), _star("c", "third")],
        [_mem("m1", "first mem")],
    )

    rewritten, _entering, meta = resolve_memory_island(
        initial,
        [_star("b", "second"), _star("a", "first"), _star("d", "new")],
        [_mem("m2", "second mem")],
        force=True,
        force_reason=reason,
    )

    assert [item["id"] for item in rewritten["stars"]] == ["b", "a", "d"]
    assert meta["star"]["reason"] == reason
    assert meta["mem"]["reason"] == reason
