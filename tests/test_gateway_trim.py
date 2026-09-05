from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from shenyu_gateway.client_extra import EXPIRED_IMAGE_MARKER, expired_image_note_text
from shenyu_gateway.context_layers import (
    assemble_layered_messages,
    expired_image_fingerprints,
    tool_safe_trim_start,
    trim_client_extra_bundle_attachments,
    trim_client_image_blocks,
    trim_client_messages,
    trim_client_tool_system_messages,
)
from shenyu_gateway.prepare_messages import (
    _assistant_lineage,
    _memory_island_force_reason,
    _resolve_client_profile,
    session_idle_seconds,
)
from shenyu_gateway.runtime import now as _now
from shenyu_gateway.context_window import (
    classify_history_event,
    compact_history_event_messages,
    insert_bridge_messages,
    normalize_history_event_messages,
    overflow_messages_for_limit,
    select_chunked_window,
)
from shenyu_gateway.tool_loop import _latest_user_text


_tool_safe_trim_start = tool_safe_trim_start


def test_assistant_lineage_records_only_hashes_and_lengths():
    result = _assistant_lineage(
        [{"role": "assistant", "content": "same reply"}],
        [{"role": "assistant", "content": "same reply"}],
    )

    assert result["available"] is True
    assert result["match"] is True
    assert result["client_chars"] == 10
    assert result["stored_chars"] == 10
    assert len(result["client_sha256"]) == 16
    assert "content" not in result


def test_assistant_lineage_detects_client_history_rewrite():
    result = _assistant_lineage(
        [{"role": "assistant", "content": "client copy changed"}],
        [{"role": "assistant", "content": "gateway original"}],
    )

    assert result["available"] is True
    assert result["match"] is False
    assert result["client_sha256"] != result["stored_sha256"]


def test_assistant_lineage_ignores_leading_echo_but_still_hashes_visible_reply():
    result = _assistant_lineage(
        [{"role": "assistant", "content": "[回响]只有客户端保留这一段。[/回响]same reply"}],
        [{"role": "assistant", "content": "same reply"}],
    )

    assert result["available"] is True
    assert result["match"] is True
    assert result["client_chars"] == 10
    assert result["stored_chars"] == 10


def test_memory_island_force_reason_covers_branch_and_message_high_water():
    assert _memory_island_force_reason(
        {"event_class": "new_user"}, {"reset_reason": "message_high_water"}
    ) == "message_high_water"
    assert _memory_island_force_reason(
        {"event_class": "branch"}, {"reset_reason": "history_branch"}
    ) == "history_branch"
    # cold_cache_rebuild 刻意不强制重写记忆岛：闲置久只是缓存凉，不是内容失效，
    # 岛照常走粘性（epoch 重置只重算锚点位置，内容保留）。
    assert _memory_island_force_reason(
        {"event_class": "new_user"}, {"reset_reason": "cold_cache_rebuild"}
    ) == ""
    assert _memory_island_force_reason(
        {"event_class": "new_user"}, {"reset_reason": ""}
    ) == ""


def test_session_idle_seconds_uses_previous_turn_last_active():
    from datetime import timedelta

    # last_active_at is still the previous turn's value when prepare opens the
    # session (touch_session runs afterwards), so idle == time since last turn.
    past = (_now() - timedelta(seconds=7200)).isoformat()
    idle = session_idle_seconds({"last_active_at": past})
    assert idle is not None
    assert 7100 <= idle <= 7300


def test_session_idle_seconds_is_none_on_first_turn():
    # No last_active_at means there is no previous turn to be cold against.
    assert session_idle_seconds({}) is None
    assert session_idle_seconds({"last_active_at": None}) is None


def test_pwa_client_profile_hides_client_tools_and_enables_tool_events():
    profile = _resolve_client_profile(
        SimpleNamespace(headers={}),
        "shenyu-pwa",
        SimpleNamespace(client_tool_surface="all"),
    )

    assert profile["client_tool_surface"] == "none"
    assert profile["emit_tool_events"] is True
    assert profile["emit_response_meta"] is True
    assert profile["emit_echo_events"] is True
    assert profile["emit_tool_event_details"] is False
    assert profile["tool_event_protocol"] == "sse+json"


def test_client_profile_only_emits_tool_details_when_explicitly_requested():
    profile = _resolve_client_profile(
        SimpleNamespace(headers={"X-Shenyu-Tool-Events": "true", "X-Shenyu-Tool-Details": "true"}),
        "another-client",
        SimpleNamespace(client_tool_surface="all"),
    )

    assert profile["emit_tool_events"] is True
    assert profile["emit_tool_event_details"] is True
    assert profile["emit_response_meta"] is False
    assert profile["emit_echo_events"] is False


def test_context_overflow_defaults_to_20_percent_with_bounds():
    assert overflow_messages_for_limit(120) == 24
    assert overflow_messages_for_limit(168) == 32
    assert overflow_messages_for_limit(220) == 40


def test_history_event_classifies_retry_new_user_tool_continuation_and_branch():
    base = [{"role": "user", "content": "u1"}]
    assert classify_history_event(base, base)["event_class"] == "retry"
    assert classify_history_event(
        base,
        base + [{"role": "assistant", "content": "a1"}, {"role": "user", "content": "u2"}],
    )["event_class"] == "new_user"
    assert classify_history_event(
        base,
        base
        + [
            {
                "role": "assistant",
                "tool_calls": [{"id": "call_a", "function": {"name": "visit_web", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "page"},
        ],
    )["event_class"] == "client_tool_continuation"
    previous = base + [{"role": "assistant", "content": "a1"}, {"role": "user", "content": "u2"}]
    branch = [{"role": "user", "content": "changed u1"}, {"role": "assistant", "content": "a1"}]
    assert classify_history_event(previous, branch)["event_class"] == "branch"


@pytest.mark.parametrize(
    ("previous", "current", "expected_class", "new_human_turn"),
    [
        (
            [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}],
            [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}],
            "retry",
            False,
        ),
        (
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
            ],
            [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}],
            "roll",
            False,
        ),
        (
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2 edited"},
            ],
            "edit_tail",
            True,
        ),
        (
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
            [
                {"role": "user", "content": "u1 changed"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
            "branch",
            True,
        ),
    ],
)
def test_history_event_table(previous, current, expected_class, new_human_turn):
    event = classify_history_event(previous, current)

    assert event["event_class"] == expected_class
    assert event["new_human_turn"] is new_human_turn


@pytest.mark.parametrize(
    ("event_class", "keeps_epoch"),
    [
        ("retry", True),
        ("roll", True),
        ("edit_tail", True),
        ("client_tool_continuation", True),
        ("continuation", True),
        ("new_user", True),
        ("branch", False),
    ],
)
def test_history_event_epoch_contract(event_class, keeps_epoch):
    messages = [{"role": "user", "content": f"m{index}"} for index in range(8)]
    previous_state = {
        "epoch_id": "epoch_existing",
        "base_limit": 6,
        "window_start_index": 2,
        "island_anchor_offset": 2,
        "island_state": {"rendered_text": "old island"},
    }

    _retained, state, meta = select_chunked_window(
        messages,
        limit=6,
        previous_state=previous_state,
        event_class=event_class,
    )

    assert (state["epoch_id"] == "epoch_existing") is keeps_epoch
    assert meta["context_epoch_reset"] is (not keeps_epoch)
    if event_class == "branch":
        assert meta["context_epoch_reset_reason"] == "history_branch"


def _alternating_history(count: int) -> list[dict]:
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"}
        for index in range(count)
    ]


def test_history_event_head_slide_is_append_not_branch():
    previous = _alternating_history(12)
    current = previous[2:] + [{"role": "user", "content": "u-new"}]

    event = classify_history_event(previous, current)

    assert event["event_class"] == "new_user"
    assert event["new_human_turn"] is True
    assert event["head_slide_messages"] == 2
    assert event["head_slide_overlap_messages"] == 10


def test_history_event_head_slide_without_new_tail_is_retry():
    previous = _alternating_history(12)

    event = classify_history_event(previous, previous[2:])

    assert event["event_class"] == "retry"
    assert event["new_human_turn"] is False
    assert event["head_slide_messages"] == 2


def test_history_event_short_head_slide_still_branches():
    previous = _alternating_history(8)
    current = previous[2:] + [{"role": "user", "content": "u-new"}]

    event = classify_history_event(previous, current)

    assert event["event_class"] == "branch"
    assert "head_slide_messages" not in event


def test_history_event_head_slide_with_inner_edit_still_branches():
    previous = _alternating_history(12)
    slid = [dict(message) for message in previous[2:]]
    slid[4]["content"] = "edited mid-history"
    current = slid + [{"role": "user", "content": "u-new"}]

    event = classify_history_event(previous, current)

    assert event["event_class"] == "branch"
    assert "head_slide_messages" not in event


def test_chunked_window_keeps_epoch_and_content_across_head_slide():
    messages = _alternating_history(170)
    _first, state, _meta = select_chunked_window(
        messages,
        limit=168,
        previous_state=None,
        event_class="initial",
    )

    slid = messages[2:] + [{"role": "user", "content": "m170"}]
    event = classify_history_event(messages, slid)
    assert event["event_class"] == "new_user"

    retained, next_state, meta = select_chunked_window(
        slid,
        limit=168,
        previous_state=state,
        event_class=event["event_class"],
        head_slide_messages=event["head_slide_messages"],
    )

    assert next_state["epoch_id"] == state["epoch_id"]
    assert meta["context_epoch_reset"] is False
    assert next_state["window_start_index"] == state["window_start_index"] - 2
    assert retained[0]["content"] == f"m{state['window_start_index']}"


def test_chunked_window_head_slide_clamps_start_to_zero():
    history = _alternating_history(76)
    previous_state = {
        "epoch_id": "epoch_existing",
        "base_limit": 75,
        "window_start_index": 166,
        "island_anchor_offset": 40,
        "island_state": {"rendered_text": "old island"},
    }

    retained, state, meta = select_chunked_window(
        history,
        limit=75,
        previous_state=previous_state,
        event_class="new_user",
        head_slide_messages=166,
    )

    assert state["epoch_id"] == "epoch_existing"
    assert meta["context_epoch_reset"] is False
    assert state["window_start_index"] == 0
    assert len(retained) == 76


def test_cold_start_bridge_deduplicates_exact_tail_against_client_history_prefix():
    bridge = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "shared question"},
        {"role": "assistant", "content": "shared answer"},
    ]
    client = [
        {"role": "system", "content": "client system"},
        {"role": "user", "content": "shared question"},
        {"role": "assistant", "content": "shared answer"},
        {"role": "user", "content": "new question"},
    ]

    merged = insert_bridge_messages(client, bridge)

    assert merged == [
        client[0],
        bridge[0],
        bridge[1],
        client[1],
        client[2],
        client[3],
    ]


def test_cold_start_bridge_does_not_deduplicate_noncontiguous_or_role_changed_text():
    bridge = [
        {"role": "user", "content": "same text"},
        {"role": "assistant", "content": "bridge answer"},
    ]
    client = [
        {"role": "assistant", "content": "same text"},
        {"role": "user", "content": "new question"},
    ]

    assert insert_bridge_messages(client, bridge) == [*bridge, *client]


def test_cold_start_bridge_removes_only_one_longest_exact_overlap():
    repeated = [
        {"role": "user", "content": "shared question"},
        {"role": "assistant", "content": "shared answer"},
    ]
    bridge = [*repeated, *repeated]
    client = [*repeated, {"role": "user", "content": "new question"}]

    assert insert_bridge_messages(client, bridge) == [*repeated, *client]


def test_history_event_ignores_expired_image_and_dynamic_bundle_changes():
    previous = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {
                    "type": "text",
                    "text": '<attachment id="message_insert_extra_bundle_old">battery 40%</attachment>',
                },
            ],
        },
        {"role": "assistant", "content": "saw it"},
    ]
    current = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "saw it"},
        {"role": "user", "content": "next"},
    ]

    stored_previous = compact_history_event_messages(previous)
    event = classify_history_event(stored_previous, current)

    assert "data:image/png;base64,abc" not in str(stored_previous)
    assert "shenyu_history_image" in str(stored_previous)
    assert event["event_class"] == "new_user"
    assert event["common_prefix_messages"] == len(previous)
    assert event["strict_common_prefix_messages"] == 2
    assert event["transient_history_changes_ignored"] is True


def test_history_event_accepts_legacy_image_placeholder_after_upgrade():
    previous = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "圆圆发来的照片我已经看过。"},
        {"role": "assistant", "content": "saw it"},
    ]
    current = compact_history_event_messages(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}],
            },
            {"role": "assistant", "content": "saw it"},
            {"role": "user", "content": "next"},
        ]
    )

    event = classify_history_event(previous, current)

    assert event["event_class"] == "new_user"
    assert event["common_prefix_messages"] == len(previous)
    assert event["strict_common_prefix_messages"] == 2
    assert event["transient_history_changes_ignored"] is True


def test_history_event_treats_expired_image_text_blocks_as_same_flattened_text():
    previous = compact_history_event_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "同一段文字"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    {
                        "type": "text",
                        "text": '<attachment id="message_insert_extra_bundle_old">old state</attachment>',
                    },
                ],
            },
            {"role": "assistant", "content": "same reply"},
            {"role": "user", "content": "same next user"},
        ]
    )
    current = [
        {
            "role": "user",
            "content": '同一段文字 <attachment id="message_insert_extra_bundle_new">new state</attachment>',
        },
        {"role": "assistant", "content": "same reply"},
        {"role": "user", "content": "same next user"},
        {"role": "assistant", "content": "new reply"},
        {"role": "user", "content": "new turn"},
    ]

    event = classify_history_event(previous, current)

    assert event["event_class"] == "new_user"
    assert event["common_prefix_messages"] == len(previous)
    assert event["transient_history_changes_ignored"] is True


def test_history_event_keeps_real_earlier_text_edit_as_branch_after_shape_normalization():
    previous = compact_history_event_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "原来的历史文字"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            },
            {"role": "assistant", "content": "same reply"},
            {"role": "user", "content": "same next user"},
        ]
    )
    current = [
        {"role": "user", "content": "被真正修改过的历史文字"},
        {"role": "assistant", "content": "same reply"},
        {"role": "user", "content": "same next user"},
        {"role": "assistant", "content": "new reply"},
        {"role": "user", "content": "new turn"},
    ]

    event = classify_history_event(previous, current)

    assert event["event_class"] == "branch"
    assert event["common_prefix_messages"] == 0
    assert event["transient_history_changes_ignored"] is False


def test_chunked_window_keeps_start_until_high_water_then_resets():
    messages = [{"role": "user", "content": f"m{index}"} for index in range(170)]
    first, state, meta = select_chunked_window(
        messages,
        limit=168,
        previous_state=None,
        event_class="initial",
    )
    assert len(first) == 168
    assert state["window_start_index"] == 2
    assert state["island_anchor_offset"] == 136
    assert meta["context_high_water"] == 200

    appended = messages + [{"role": "user", "content": f"m{index}"} for index in range(170, 200)]
    second, same_epoch, second_meta = select_chunked_window(
        appended,
        limit=168,
        previous_state=state,
        event_class="new_user",
    )
    assert len(second) == 198
    assert same_epoch["epoch_id"] == state["epoch_id"]
    assert second_meta["context_epoch_reset"] is False

    overflowed = appended + [
        {"role": "user", "content": "m200"},
        {"role": "assistant", "content": "a200"},
        {"role": "user", "content": "m201"},
    ]
    third, reset_state, third_meta = select_chunked_window(
        overflowed,
        limit=168,
        previous_state=same_epoch,
        event_class="new_user",
    )
    assert len(third) == 168
    assert reset_state["epoch_id"] != state["epoch_id"]
    assert third_meta["context_epoch_reset_reason"] == "message_high_water"


def _cold_cache_state():
    messages = [{"role": "user", "content": f"m{index}"} for index in range(10)]
    _first, state, _meta = select_chunked_window(
        messages,
        limit=168,
        previous_state=None,
        event_class="initial",
    )
    # One more turn so there is a live epoch to either keep or roll.
    appended = messages + [{"role": "user", "content": "m10"}]
    return appended, state


def test_chunked_window_rolls_epoch_when_cache_is_cold():
    appended, state = _cold_cache_state()
    _second, next_state, meta = select_chunked_window(
        appended,
        limit=168,
        previous_state=state,
        event_class="new_user",
        idle_seconds=3600,
        cold_cache_threshold_seconds=3600,
    )
    assert next_state["epoch_id"] != state["epoch_id"]
    assert meta["context_epoch_reset_reason"] == "cold_cache_rebuild"


def test_chunked_window_keeps_epoch_when_cache_is_still_warm():
    appended, state = _cold_cache_state()
    _second, next_state, meta = select_chunked_window(
        appended,
        limit=168,
        previous_state=state,
        event_class="new_user",
        idle_seconds=120,
        cold_cache_threshold_seconds=3600,
    )
    assert next_state["epoch_id"] == state["epoch_id"]
    assert meta["context_epoch_reset"] is False


def test_chunked_window_ignores_cold_cache_when_toggle_is_off():
    appended, state = _cold_cache_state()
    # Toggle off is wired as threshold=None: the cold-cache branch never fires
    # even when idle far exceeds any TTL.
    _second, next_state, _meta = select_chunked_window(
        appended,
        limit=168,
        previous_state=state,
        event_class="new_user",
        idle_seconds=999_999,
        cold_cache_threshold_seconds=None,
    )
    assert next_state["epoch_id"] == state["epoch_id"]


def test_chunked_window_does_not_roll_on_first_turn_without_idle():
    messages = [{"role": "user", "content": f"m{index}"} for index in range(10)]
    # idle_seconds=None models the first turn (no previous last_active_at); the
    # cold-cache branch must not treat "no history" as "infinitely cold".
    _first, state, meta = select_chunked_window(
        messages,
        limit=168,
        previous_state=None,
        event_class="initial",
        idle_seconds=None,
        cold_cache_threshold_seconds=3600,
    )
    assert meta["context_epoch_reset_reason"] != "cold_cache_rebuild"


def test_chunked_window_never_splits_latest_tool_group():
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "read it"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "call_a", "function": {"name": "read_file", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "file"},
    ]
    selected, state, _meta = select_chunked_window(
        messages,
        limit=2,
        previous_state=None,
        event_class="initial",
    )
    assert [message["role"] for message in selected] == ["user", "assistant", "tool"]
    assert state["raw_protected_turns"] == 1


def test_tool_safe_trim_start_includes_user_and_assistant_for_retained_tool_result():
    messages = [
        {"role": "user", "content": "before"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
                {"id": "call_b", "type": "function", "function": {"name": "grep_code", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "a"},
        {"role": "tool", "tool_call_id": "call_b", "content": "b"},
        {"role": "user", "content": "after"},
    ]

    assert _tool_safe_trim_start(messages, 2) == 0


def test_trim_client_messages_keeps_user_prompt_before_latest_tool_turn():
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "can you see the folder?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "list_files", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "folder listing"},
    ]

    trimmed, meta = trim_client_messages(messages, 2)

    assert [msg["role"] for msg in trimmed] == ["assistant", "user", "assistant", "tool"]
    assert trimmed[1]["content"] == "can you see the folder?"
    assert meta["client_messages_retained"] == 4
    assert meta["client_tool_tail_messages"] == 2


def test_trim_client_messages_preserves_original_prompt_window_before_tool_tail():
    messages = [
        {"role": "user", "content": f"old {idx}"}
        for idx in range(82)
    ]
    messages.extend(
        [
            {"role": "user", "content": "can you see the folder?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_a", "type": "function", "function": {"name": "list_files", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "folder listing"},
        ]
    )

    trimmed, meta = trim_client_messages(messages, 80)

    assert len(trimmed) == 82
    assert trimmed[0]["content"] == "old 3"
    assert trimmed[-3]["content"] == "can you see the folder?"
    assert trimmed[-2]["tool_calls"][0]["id"] == "call_a"
    assert trimmed[-1]["tool_call_id"] == "call_a"
    assert meta["client_messages_retained"] == 82
    assert meta["client_tool_tail_messages"] == 2


def test_trim_client_tool_system_messages_drops_operit_tool_prompt_when_hidden():
    client_tool_prompt = """调用工具时，用户会看到你的响应，然后会自动将工具结果发送回给你。

使用工具时，请使用以下格式：

<tool name="tool_name">
<param name="parameter_name">parameter_value</param>
</tool>

包系统：
- 一些额外功能通过包提供

Available packages:
- code_runner : run code

可用工具:
- use_package

文件系统工具:
- read_file

HTTP工具:
- visit_web
"""
    messages = [
        {"role": "system", "content": "regular system prompt"},
        {"role": "system", "content": client_tool_prompt},
        {"role": "user", "content": "hello"},
    ]

    trimmed, meta = trim_client_tool_system_messages(messages, surface="none")

    assert [msg["content"] for msg in trimmed] == ["regular system prompt", "hello"]
    assert meta["client_tool_surface"] == "none"
    assert meta["client_tool_system_messages_seen"] == 1
    assert meta["client_tool_system_messages_trimmed"] == 1
    assert meta["client_tool_system_messages_rewritten"] == 0


def test_trim_client_tool_system_messages_keeps_regular_system_prompt():
    messages = [
        {"role": "system", "content": "请在需要时使用工具，但先解释你的判断。"},
        {"role": "user", "content": "hello"},
    ]

    trimmed, meta = trim_client_tool_system_messages(messages, surface="none")

    assert trimmed == messages
    assert meta["client_tool_system_messages_seen"] == 0
    assert meta["client_tool_system_messages_trimmed"] == 0


def test_trim_client_tool_system_messages_guards_all_surface_without_removing_catalog():
    messages = [
        {
            "role": "system",
            "content": "包系统：\nAvailable packages:\nTo use a package:\n<tool name=\"use_package\">",
        },
        {"role": "user", "content": "hello"},
    ]

    trimmed, meta = trim_client_tool_system_messages(messages, surface="all")

    assert len(trimmed) == 2
    assert "Available packages:" in trimmed[0]["content"]
    assert "网关覆盖规则" in trimmed[0]["content"]
    assert "<tool name=\"shenyu_gateway_tool\">" in trimmed[0]["content"]
    assert meta["client_tool_system_messages_seen"] == 1
    assert meta["client_tool_system_messages_trimmed"] == 0
    assert meta["client_tool_system_messages_guarded"] == 1


def test_trim_client_tool_system_messages_rewrites_daily_surface_to_daily_catalog():
    messages = [
        {
            "role": "system",
            "content": "调用工具时，用户会看到你的响应\n使用工具时，请使用以下格式：\n"
            "<tool name=\"tool_name\">\nAvailable packages:\n- workflow\n- code_runner\n"
            "文件系统工具:\n- create_file\nHTTP工具:\n- download_file",
        },
        {
            "role": "system",
            "content": "包系统：\nAvailable packages:\nTo use a package:\n<tool name=\"use_package\">",
        },
        {"role": "user", "content": "hello"},
    ]

    trimmed, meta = trim_client_tool_system_messages(messages, surface="daily")

    assert len(trimmed) == 2
    daily_prompt = trimmed[0]["content"]
    assert "客户端工具（日常桌面）" in daily_prompt
    assert "- read_file" in daily_prompt
    assert "- visit_web" in daily_prompt
    assert "coread_*" in daily_prompt
    assert "code_runner" in daily_prompt
    assert "不要使用" in daily_prompt
    assert "create_file" in daily_prompt
    assert "网关覆盖规则" in daily_prompt
    assert trimmed[1]["content"] == "hello"
    assert meta["client_tool_surface"] == "daily"
    assert meta["client_tool_system_messages_seen"] == 2
    assert meta["client_tool_system_messages_rewritten"] == 1
    assert meta["client_tool_system_messages_trimmed"] == 1


def test_tool_safe_trim_start_drops_incomplete_assistant_tool_turn():
    messages = [
        {"role": "user", "content": "before"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
                {"id": "call_b", "type": "function", "function": {"name": "grep_code", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "a"},
        {"role": "user", "content": "after"},
    ]

    assert _tool_safe_trim_start(messages, 1) == 3


def test_mem_island_sits_after_system_layers_before_recent_chat_history():
    client_messages = [{"role": "user", "content": "hello"}]
    layers = {
        "stable": "stable block",
        "slow": "## Calendar Memory\ncalendar block",
        "mem": "## 我之前写下的便签，可能用的到。\n- mem block",
        "heartbeat": "## 我之前的心跳\nheartbeat block",
        "tool_policy": "## 工具怎么用\ntool block",
        "format": "## Heartbeat\nformat block",
        "volatile": "",
    }

    messages, meta = assemble_layered_messages(client_messages, layers)

    assert meta == {"memory_island_insert_index": 5, "memory_island_anchor_offset": 0}
    assert [msg["content"] for msg in messages] == [
        "stable block",
        "## Calendar Memory\ncalendar block",
        "## 我之前的心跳\nheartbeat block",
        "## 工具怎么用\ntool block",
        "## Heartbeat\nformat block",
        "## 我之前写下的便签，可能用的到。\n- mem block",
        "hello",
    ]
    assert messages[-2]["_shenyu_context_layer"] == "memory_island"


def test_trim_client_extra_bundle_attachments_keeps_latest_three_user_bundles():
    messages = [
        {
            "role": "user",
            "content": f"msg {idx} <attachment id=\"message_insert_extra_bundle_{idx}\" filename=\"Time\" "
            "type=\"text/plain\">battery weather time</attachment>",
        }
        for idx in range(5)
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=3)

    assert meta["client_attachment_messages_seen"] == 5
    assert meta["client_attachment_messages_trimmed"] == 2
    assert meta["client_attachment_blocks_trimmed"] == 2
    assert "message_insert_extra_bundle" not in trimmed[0]["content"]
    assert "message_insert_extra_bundle" not in trimmed[1]["content"]
    assert trimmed[0]["content"] == "msg 0"
    assert trimmed[1]["content"] == "msg 1"
    assert "message_insert_extra_bundle_2" in trimmed[2]["content"]
    assert "message_insert_extra_bundle_4" in trimmed[4]["content"]


def test_trim_client_extra_bundle_attachments_preserves_images_and_user_text_blocks():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {
                    "type": "text",
                    "text": "cake <attachment id=\"message_insert_extra_bundle_old\" "
                    "filename=\"Time\" type=\"text/plain\">device state</attachment>",
                },
            ],
        },
        {
            "role": "assistant",
            "content": "<attachment id=\"message_insert_extra_bundle_assistant\">leave me</attachment>",
        },
        {
            "role": "user",
            "content": "latest <attachment id=\"message_insert_extra_bundle_new\">keep</attachment>",
        },
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=1)

    assert meta["client_attachment_messages_seen"] == 2
    assert meta["client_attachment_messages_trimmed"] == 1
    assert trimmed[0]["content"][0]["type"] == "image_url"
    assert trimmed[0]["content"][1]["text"] == "cake"
    assert "message_insert_extra_bundle_assistant" in trimmed[1]["content"]
    assert "message_insert_extra_bundle_new" in trimmed[2]["content"]


_PWA_STATUS_SUFFIX = "【26/07 周日 14:30 · 第140天 · 🔋80%⚡ · 邵阳 霾 25℃】"


def test_trim_keeps_latest_three_pwa_status_suffix_messages():
    messages = [
        {"role": "user", "content": f"晚安 {idx} {_PWA_STATUS_SUFFIX}"} for idx in range(5)
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=3)

    assert meta["client_attachment_messages_seen"] == 5
    assert meta["client_attachment_messages_trimmed"] == 2
    assert meta["client_attachment_blocks_trimmed"] == 2
    assert trimmed[0]["content"] == "晚安 0"
    assert trimmed[1]["content"] == "晚安 1"
    for idx in (2, 3, 4):
        assert trimmed[idx]["content"] == f"晚安 {idx} {_PWA_STATUS_SUFFIX}"


def test_trim_counts_attachment_and_pwa_suffix_messages_together():
    messages = [
        {"role": "user", "content": f"我在读【小王子】呢 {_PWA_STATUS_SUFFIX}"},
        {
            "role": "user",
            "content": "带附件 <attachment id=\"message_insert_extra_bundle_a\">state</attachment>"
            f" {_PWA_STATUS_SUFFIX}",
        },
        {"role": "user", "content": f"第三条 {_PWA_STATUS_SUFFIX}"},
        {
            "role": "user",
            "content": "第四条 <attachment id=\"message_insert_extra_bundle_b\">state</attachment>",
        },
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=2)

    assert meta["client_attachment_messages_seen"] == 4
    assert meta["client_attachment_messages_trimmed"] == 2
    # message 0 loses only its suffix (ordinary 【书名】 stays); message 1 loses
    # its attachment block and its suffix in the same pass.
    assert meta["client_attachment_blocks_trimmed"] == 3
    assert trimmed[0]["content"] == "我在读【小王子】呢"
    assert trimmed[1]["content"] == "带附件"
    assert trimmed[2]["content"] == f"第三条 {_PWA_STATUS_SUFFIX}"
    assert "message_insert_extra_bundle_b" in trimmed[3]["content"]


def test_trim_ignores_plain_brackets_and_non_tail_status_text():
    messages = [
        {"role": "user", "content": "我在读【小王子】这本书，很好看"},
        {"role": "user", "content": f"{_PWA_STATUS_SUFFIX} 后面还有正文，所以这不算状态后缀"},
        {"role": "user", "content": "第三条普通消息"},
        {"role": "user", "content": "第四条普通消息"},
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=3)

    assert meta["client_attachment_messages_seen"] == 0
    assert meta["client_attachment_messages_trimmed"] == 0
    assert trimmed == messages


def test_trim_strips_stacked_pwa_suffixes_from_older_messages():
    messages = [
        {"role": "user", "content": f"早安 {_PWA_STATUS_SUFFIX}{_PWA_STATUS_SUFFIX}"},
        *[
            {"role": "user", "content": f"晚安 {idx} {_PWA_STATUS_SUFFIX}"}
            for idx in range(3)
        ],
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=3)

    assert meta["client_attachment_messages_seen"] == 4
    assert meta["client_attachment_messages_trimmed"] == 1
    assert meta["client_attachment_blocks_trimmed"] == 2
    assert trimmed[0]["content"] == "早安"


def test_strip_client_extra_text_clears_stacked_suffixes():
    from shenyu_gateway.client_extra import strip_client_extra_text

    cleaned, removed = strip_client_extra_text(
        f"早安 {_PWA_STATUS_SUFFIX} {_PWA_STATUS_SUFFIX}"
    )

    assert cleaned == "早安"
    assert removed == 2


def test_trim_pwa_suffix_leaves_assistant_messages_alone():
    messages = [
        {"role": "user", "content": f"用户 0 {_PWA_STATUS_SUFFIX}"},
        {"role": "assistant", "content": f"助手也带着 {_PWA_STATUS_SUFFIX}"},
        {"role": "user", "content": f"用户 1 {_PWA_STATUS_SUFFIX}"},
        {"role": "user", "content": f"用户 2 {_PWA_STATUS_SUFFIX}"},
        {"role": "user", "content": f"用户 3 {_PWA_STATUS_SUFFIX}"},
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=3)

    assert meta["client_attachment_messages_seen"] == 4
    assert meta["client_attachment_messages_trimmed"] == 1
    assert trimmed[0]["content"] == "用户 0"
    assert trimmed[1]["content"] == f"助手也带着 {_PWA_STATUS_SUFFIX}"
    assert trimmed[2]["content"] == f"用户 1 {_PWA_STATUS_SUFFIX}"


def test_trim_pwa_suffix_strips_tail_of_text_blocks():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {"type": "text", "text": f"看这张照片 {_PWA_STATUS_SUFFIX}"},
            ],
        },
        {"role": "user", "content": f"新的一条 {_PWA_STATUS_SUFFIX}"},
    ]

    trimmed, meta = trim_client_extra_bundle_attachments(messages, keep_recent_messages=1)

    assert meta["client_attachment_messages_seen"] == 2
    assert meta["client_attachment_messages_trimmed"] == 1
    assert trimmed[0]["content"][0]["type"] == "image_url"
    assert trimmed[0]["content"][1]["text"] == "看这张照片"
    assert trimmed[1]["content"] == f"新的一条 {_PWA_STATUS_SUFFIX}"


def test_trim_client_image_blocks_keeps_latest_two_image_messages():
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,img{idx}"}}],
        }
        for idx in range(4)
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=2)

    assert meta["client_image_messages_seen"] == 4
    assert meta["client_image_messages_trimmed"] == 2
    assert meta["client_image_blocks_trimmed"] == 2
    assert meta["client_image_placeholders_added"] == 2
    assert trimmed[0]["content"] == "圆圆发来的照片我已经看过。"
    assert trimmed[1]["content"] == "圆圆发来的照片我已经看过。"
    assert trimmed[2]["content"][0]["image_url"]["url"] == "data:image/png;base64,img2"
    assert trimmed[3]["content"][0]["image_url"]["url"] == "data:image/png;base64,img3"


def test_trim_client_image_blocks_preserves_text_from_old_image_message():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "圆圆说这个小身体很重。"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,old"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,new"}}],
        },
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=1)

    assert meta["client_image_messages_trimmed"] == 1
    assert trimmed[0]["content"] == [{"type": "text", "text": "圆圆说这个小身体很重。"}]
    assert trimmed[1]["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,new"


def test_trim_client_image_blocks_expires_single_image_after_two_newer_user_turns():
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,old"}}],
        },
        {"role": "assistant", "content": "seen"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "third user turn"},
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=2)

    assert meta["client_image_keep_user_turns"] == 2
    assert meta["client_image_messages_seen"] == 1
    assert meta["client_image_messages_trimmed"] == 1
    assert trimmed[0]["content"] == "圆圆发来的照片我已经看过。"


def test_trim_client_image_blocks_can_remove_all_images_for_storage():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看这个。"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,def"}}],
        },
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=0)

    assert meta["client_image_messages_trimmed"] == 2
    assert meta["client_image_blocks_trimmed"] == 2
    assert trimmed[0]["content"] == [{"type": "text", "text": "看这个。"}]
    assert trimmed[1]["content"] == "圆圆发来的照片我已经看过。"


def _expired(fingerprint: str) -> dict:
    return {"type": "image", "source": {"type": EXPIRED_IMAGE_MARKER, "fingerprint": fingerprint}}


# 2026-08-30 的实际缺陷：PWA 送来的过期占位块落在「最近两轮」里时不参与替换，
# 于是被原样转给上游——那是个上游不认识的 image block，Anthropic 直接报错。
# 触发路径真实存在：沈予编辑一条旧消息重发，那条就成了最新一轮，而它的图早已
# 本机过期。占位块里根本没有图，「保留最近两轮的图」对它不适用。
def test_expired_image_marker_never_reaches_upstream_even_in_the_newest_turn():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "改写这条"}, _expired("aa")]},
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=2)

    assert meta["client_image_expired_markers_seen"] == 1
    assert meta["client_image_messages_trimmed"] == 1
    serialized = json.dumps(trimmed, ensure_ascii=False)
    assert EXPIRED_IMAGE_MARKER not in serialized
    # 这一轮说过的话一个字都不能少。
    assert "改写这条" in serialized


# 2026-08-30 外部审阅抓到的回归，方向与上一条相反：占位块把整条消息拉进替换
# 流程，而剥离是消息级的，于是同一条消息里仍带字节的真图被连带剥掉——沈予看不到
# 那张本该送到的图。触发路径同上：编辑一条带两张图的旧消息重发，其中一张已被
# 本机 30 张上限淘汰。
def test_a_live_photo_survives_beside_an_expired_marker_in_the_same_turn():
    live = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,STILL_HERE"}}
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "改写这条"}, _expired("aa"), live]},
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=2)

    serialized = json.dumps(trimmed, ensure_ascii=False)
    # 占位块必须走（否则上游报错），真图必须留（否则他看不到这张图）。
    assert EXPIRED_IMAGE_MARKER not in serialized
    assert "STILL_HERE" in serialized
    assert "改写这条" in serialized
    assert meta["client_image_blocks_trimmed"] == 1


def test_a_live_photo_survives_and_the_album_note_still_arrives():
    live = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,STILL_HERE"}}
    notes = {"aa": expired_image_note_text("海边那天的光")}
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "还记得这张吗"}, _expired("aa"), live]},
    ]

    trimmed, _ = trim_client_image_blocks(messages, keep_recent_messages=2, album_notes=notes)

    serialized = json.dumps(trimmed, ensure_ascii=False)
    assert "STILL_HERE" in serialized
    assert "海边那天的光" in serialized


def test_outside_the_keep_window_a_live_photo_is_still_trimmed():
    """窗口外的老行为不能被这次修复放松。"""
    live = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,OLD"}}
    messages = [
        {"role": "user", "content": [live]},
        {"role": "assistant", "content": "seen"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "third"},
    ]

    trimmed, _ = trim_client_image_blocks(messages, keep_recent_messages=2)

    assert trimmed[0]["content"] == "圆圆发来的照片我已经看过。"


def test_one_saved_and_one_unsaved_photo_both_leave_a_trace():
    """外部审阅指出的第三点：没存过的那张原先会被静默吞掉。"""
    notes = {"aa": expired_image_note_text("海边那天的光")}
    messages = [{"role": "user", "content": [_expired("aa"), _expired("bb")]}]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=0, album_notes=notes)

    assert trimmed[0]["content"].splitlines() == [
        "圆圆发来的照片我已经看过。——海边那天的光",
        "圆圆发来的照片我已经看过。",
    ]
    assert meta["client_image_album_notes_used"] == 1


def test_expired_image_marker_is_replaced_by_what_shenyu_wrote_in_his_album():
    notes = {"aa": expired_image_note_text("海边那天的光落在她手上", "安静")}
    messages = [
        {"role": "user", "content": [_expired("aa")]},
        {"role": "assistant", "content": "记得"},
        {"role": "user", "content": "后来呢"},
    ]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=2, album_notes=notes)

    assert meta["client_image_album_notes_used"] == 1
    assert trimmed[0]["content"] == "圆圆发来的照片我已经看过。——海边那天的光落在她手上｜安静"


def test_album_note_still_reaches_the_model_when_the_turn_also_has_text():
    """带文字的消息也要送到他写的那句，否则「读到自己的描述」在这种消息里落空。"""
    notes = {"aa": expired_image_note_text("那天很亮")}
    messages = [{"role": "user", "content": [{"type": "text", "text": "还记得这张吗"}, _expired("aa")]}]

    trimmed, _ = trim_client_image_blocks(messages, keep_recent_messages=0, album_notes=notes)

    texts = [block["text"] for block in trimmed[0]["content"] if block.get("type") == "text"]
    assert texts == ["还记得这张吗", "圆圆发来的照片我已经看过。——那天很亮"]


def test_unsaved_expired_image_falls_back_to_the_generic_placeholder():
    messages = [{"role": "user", "content": [_expired("never-saved")]}]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=0, album_notes={"other": "x"})

    assert trimmed[0]["content"] == "圆圆发来的照片我已经看过。"
    assert meta["client_image_album_notes_used"] == 0


def test_several_saved_photos_in_one_turn_keep_one_line_each():
    notes = {
        "aa": expired_image_note_text("第一张"),
        "bb": expired_image_note_text("第二张"),
    }
    messages = [{"role": "user", "content": [_expired("aa"), _expired("bb")]}]

    trimmed, meta = trim_client_image_blocks(messages, keep_recent_messages=0, album_notes=notes)

    assert meta["client_image_album_notes_used"] == 2
    assert trimmed[0]["content"].splitlines() == [
        "圆圆发来的照片我已经看过。——第一张",
        "圆圆发来的照片我已经看过。——第二张",
    ]


def test_expired_image_fingerprints_are_collected_once_in_order():
    messages = [
        {"role": "user", "content": [_expired("aa"), _expired("bb")]},
        {"role": "assistant", "content": [_expired("zz")]},
        {"role": "user", "content": [_expired("aa"), _expired("cc")]},
    ]

    # 助手消息里的不算；重复只出现一次，顺序稳定（便于批量查库）。
    assert expired_image_fingerprints(messages) == ["aa", "bb", "cc"]
    assert expired_image_fingerprints([]) == []


# 这条守的是整批改动里最容易静默出事的东西：换成动态描述后，历史归一化必须仍把
# 占位当成空，否则沈予每换一句话都会被分支检测判成 branch，白扔掉整个 prompt
# cache epoch。
def test_album_note_placeholder_stays_invisible_to_branch_detection():
    def with_image(url: str) -> list[dict]:
        return [
            {"role": "user", "content": [
                {"type": "text", "text": "看这个"},
                {"type": "image_url", "image_url": {"url": url}},
            ]},
        ]

    real = with_image("data:image/jpeg;base64,AAAA")
    trimmed_generic, _ = trim_client_image_blocks(
        [{"role": "user", "content": [{"type": "text", "text": "看这个"}, _expired("aa")]}],
        keep_recent_messages=0,
    )
    trimmed_note, _ = trim_client_image_blocks(
        [{"role": "user", "content": [{"type": "text", "text": "看这个"}, _expired("aa")]}],
        keep_recent_messages=0,
        album_notes={"aa": expired_image_note_text("海边那天的光")},
    )
    other_note, _ = trim_client_image_blocks(
        [{"role": "user", "content": [{"type": "text", "text": "看这个"}, _expired("aa")]}],
        keep_recent_messages=0,
        album_notes={"aa": expired_image_note_text("换了一句完全不同的话")},
    )

    baseline = normalize_history_event_messages(real)
    assert normalize_history_event_messages(trimmed_generic) == baseline
    assert normalize_history_event_messages(trimmed_note) == baseline
    # 换一句描述不改变归一化结果 —— 这正是 epoch 不被重置的原因。
    assert normalize_history_event_messages(other_note) == baseline

    assert classify_history_event(real, trimmed_note)["event_class"] == "retry"
    assert classify_history_event(trimmed_note, other_note)["event_class"] == "retry"


# 前缀判断的真实触发入口，2026-08-30 外部审阅追问后查清：分类阶段跑在图片裁剪
# 之前，所以线上主路径看到的是 marker 块，保 epoch 的是图片块判别器。而快照写在
# 裁剪之后，存的是替换后的文字；PWA 交接时把快照当历史送回来，那时分类才会看到
# 沈予那句话——所以「认前缀不认整句」在这条路上是活的，不是纯防御。
def test_snapshot_handoff_with_different_album_notes_keeps_the_epoch():
    turn = [{"role": "user", "content": [{"type": "text", "text": "看这个"}, _expired("aa")]}]

    # 快照写入用 keep_recent_messages=0（与 prepare_messages 一致）。
    snapshot_a, _ = trim_client_image_blocks(
        turn, keep_recent_messages=0, album_notes={"aa": expired_image_note_text("海边那天的光")},
    )
    snapshot_b, _ = trim_client_image_blocks(
        turn, keep_recent_messages=0, album_notes={"aa": expired_image_note_text("完全换了一句别的话")},
    )

    assert snapshot_a != snapshot_b
    assert normalize_history_event_messages(snapshot_a) == normalize_history_event_messages(snapshot_b)
    assert classify_history_event(snapshot_a, snapshot_b)["event_class"] == "retry"


def test_latest_user_text_ignores_image_urls():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看这个。"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }
    ]

    assert _latest_user_text(messages) == "看这个。"


def _plain_history(count: int) -> list[dict]:
    """Alternating turns, so a group-safe anchor can land anywhere."""
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"}
        for index in range(count)
    ]


def test_island_tail_messages_moves_the_anchor_on_a_fresh_window():
    messages = _plain_history(100)

    _default, default_state, _ = select_chunked_window(
        messages, limit=None, previous_state=None, event_class="initial"
    )
    _narrow, narrow_state, narrow_meta = select_chunked_window(
        messages,
        limit=None,
        previous_state=None,
        event_class="initial",
        island_tail_messages=20,
    )

    # The island hangs this many messages from the end, so a smaller tail pushes
    # the anchor later in the history.
    assert default_state["island_anchor_offset"] == 100 - 32
    assert narrow_state["island_anchor_offset"] == 100 - 20
    assert narrow_meta["memory_island_anchor_offset"] == 80


def test_a_changed_island_tail_waits_for_an_epoch_boundary():
    messages = _plain_history(100)
    _first, state, _ = select_chunked_window(
        messages, limit=None, previous_state=None, event_class="initial"
    )
    assert state["island_anchor_offset"] == 68

    # Same epoch: the stored anchor is reused, so the new setting is not applied
    # yet. Applying it mid-epoch would move the cache prefix and burn the whole
    # window's cache on a settings change.
    _second, same_epoch, _ = select_chunked_window(
        messages + _plain_history(2),
        limit=None,
        previous_state=state,
        event_class="new_user",
        island_tail_messages=20,
    )
    assert same_epoch["epoch_id"] == state["epoch_id"]
    assert same_epoch["island_anchor_offset"] == 68

    # A branch resets the epoch, and only then does the new tail take effect.
    _third, reset_state, _ = select_chunked_window(
        messages,
        limit=None,
        previous_state=same_epoch,
        event_class="branch",
        island_tail_messages=20,
    )
    assert reset_state["epoch_id"] != state["epoch_id"]
    assert reset_state["island_anchor_offset"] == 80
