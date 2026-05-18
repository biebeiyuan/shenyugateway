from __future__ import annotations

from shenyu_gateway.context_layers import assemble_layered_messages, tool_safe_trim_start


_tool_safe_trim_start = tool_safe_trim_start


def test_tool_safe_trim_start_includes_assistant_for_retained_tool_result():
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

    assert _tool_safe_trim_start(messages, 2) == 1


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
