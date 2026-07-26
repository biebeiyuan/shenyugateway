from __future__ import annotations

from types import SimpleNamespace

import pytest

from shenyu_gateway.context_layers import (
    assemble_layered_messages,
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
)
from shenyu_gateway.context_window import (
    classify_history_event,
    compact_history_event_messages,
    insert_bridge_messages,
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


def test_memory_island_force_reason_covers_branch_and_message_high_water():
    assert _memory_island_force_reason(
        {"event_class": "new_user"}, {"reset_reason": "message_high_water"}
    ) == "message_high_water"
    assert _memory_island_force_reason(
        {"event_class": "branch"}, {"reset_reason": "history_branch"}
    ) == "history_branch"
    assert _memory_island_force_reason(
        {"event_class": "new_user"}, {"reset_reason": ""}
    ) == ""


def test_pwa_client_profile_hides_client_tools_and_enables_tool_events():
    profile = _resolve_client_profile(
        SimpleNamespace(headers={}),
        "shenyu-pwa",
        SimpleNamespace(client_tool_surface="all"),
    )

    assert profile["client_tool_surface"] == "none"
    assert profile["emit_tool_events"] is True
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
