from __future__ import annotations

from shenyu_gateway.context_layers import (
    assemble_layered_messages,
    tool_safe_trim_start,
    trim_client_extra_bundle_attachments,
    trim_client_messages,
)


_tool_safe_trim_start = tool_safe_trim_start


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


def test_heartbeat_layer_sits_after_calendar_before_chat_history():
    client_messages = [{"role": "user", "content": "hello"}]
    layers = {
        "stable": "stable block",
        "slow": "## Calendar Memory\ncalendar block",
        "heartbeat": "## 你之前的心跳\nheartbeat block",
        "volatile": "",
    }

    messages, meta = assemble_layered_messages(client_messages, layers)

    assert meta == {}
    assert [msg["content"] for msg in messages] == [
        "stable block",
        "## Calendar Memory\ncalendar block",
        "## 你之前的心跳\nheartbeat block",
        "hello",
    ]


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
