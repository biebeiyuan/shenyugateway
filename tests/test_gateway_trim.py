from __future__ import annotations

from shenyu_gateway.context_layers import (
    assemble_layered_messages,
    tool_safe_trim_start,
    trim_client_extra_bundle_attachments,
    trim_client_image_blocks,
    trim_client_messages,
)
from shenyu_gateway.tool_loop import _latest_user_text


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


def test_mem_and_heartbeat_layers_sit_after_calendar_before_tools_and_chat_history():
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

    assert meta == {}
    assert [msg["content"] for msg in messages] == [
        "stable block",
        "## Calendar Memory\ncalendar block",
        "## 我之前写下的便签，可能用的到。\n- mem block",
        "## 我之前的心跳\nheartbeat block",
        "## 工具怎么用\ntool block",
        "## Heartbeat\nformat block",
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
