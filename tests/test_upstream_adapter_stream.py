from __future__ import annotations

import json

from shenyu_gateway.upstream_adapter import (
    ANTHROPIC_CONTENT_BLOCKS_KEY,
    _assistant_tool_call_message,
    _cache_usage_summary,
    _anthropic_tool_index_override,
    _anthropic_to_openai_chunk,
    _anthropic_to_openai_completion,
    _completion_to_stream_events,
    _openai_to_anthropic,
)
from shenyu_gateway.upstream_client import (
    _anthropic_content_blocks_snapshot,
    _update_anthropic_content_blocks,
)


def _stream_payloads(completion: dict):
    payloads = []
    for event in _completion_to_stream_events(completion):
        for line in event.splitlines():
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            payloads.append("[DONE]" if data == "[DONE]" else json.loads(data))
    return payloads


def test_anthropic_tool_completion_preserves_opaque_thinking_for_tool_continuation():
    response = {
        "content": [
            {"type": "thinking", "thinking": "summary", "signature": "opaque-signature"},
            {"type": "text", "text": "I will check."},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.txt"}},
        ],
        "stop_reason": "tool_use",
        "usage": {},
    }

    completion = _anthropic_to_openai_completion("test-model", response)
    assistant_message = completion["choices"][0]["message"]
    tool_calls = assistant_message["tool_calls"]
    continuation_message = _assistant_tool_call_message(assistant_message, tool_calls)
    _, anthropic_messages = _openai_to_anthropic(
        [
            continuation_message,
            {"role": "tool", "tool_call_id": "toolu_1", "content": "file body"},
        ]
    )

    assert assistant_message["reasoning_content"] == "summary"
    assert assistant_message[ANTHROPIC_CONTENT_BLOCKS_KEY] == response["content"]
    assert anthropic_messages[0]["content"] == response["content"]
    assert anthropic_messages[1]["content"][0]["type"] == "tool_result"


def test_anthropic_stream_reconstructs_signature_and_tool_input_blocks():
    blocks = {}
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "summary"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "opaque"}},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": "{\"path\":\"a.txt\"}"},
        },
        {"type": "content_block_stop", "index": 1},
    ]

    for event in events:
        _update_anthropic_content_blocks(blocks, event)

    snapshot = _anthropic_content_blocks_snapshot(blocks)
    assert snapshot == [
        {"type": "thinking", "thinking": "summary", "signature": "opaque"},
        {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.txt"}},
    ]


def test_completion_stream_events_forward_tool_calls():
    completion = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "reasoning_content": "need a file",
                    "content": "I will check.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": "{\"path\":\"notes.txt\"}",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    payloads = _stream_payloads(completion)

    assert payloads[0]["choices"][0]["delta"]["role"] == "assistant"
    assert payloads[1]["choices"][0]["delta"]["reasoning_content"] == "need a file"
    assert payloads[2]["choices"][0]["delta"]["content"] == "I will check."
    tool_delta = payloads[3]["choices"][0]["delta"]["tool_calls"][0]
    assert tool_delta["index"] == 0
    assert tool_delta["id"] == "call_1"
    assert tool_delta["function"]["name"] == "read_file"
    assert tool_delta["function"]["arguments"] == "{\"path\":\"notes.txt\"}"
    assert payloads[4]["choices"][0]["finish_reason"] == "tool_calls"
    assert payloads[-1] == "[DONE]"


def test_completion_stream_events_handle_tool_only_reply():
    completion = {
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {"name": "grep_code", "arguments": {"pattern": "TODO"}},
                        }
                    ],
                }
            }
        ],
    }

    payloads = _stream_payloads(completion)

    tool_delta = next(
        payload["choices"][0]["delta"]["tool_calls"][0]
        for payload in payloads
        if payload != "[DONE]" and payload["choices"][0]["delta"].get("tool_calls")
    )
    assert tool_delta["function"]["name"] == "grep_code"
    assert json.loads(tool_delta["function"]["arguments"]) == {"pattern": "TODO"}
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert payloads[-1] == "[DONE]"


def test_completion_stream_events_can_skip_role_and_chunk_content():
    completion = {
        "created": 123,
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": "abcdef"}}],
    }

    payloads = []
    for event in _completion_to_stream_events(completion, include_role=False, content_chunk_chars=2):
        for line in event.splitlines():
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            payloads.append("[DONE]" if data == "[DONE]" else json.loads(data))

    deltas = [payload["choices"][0]["delta"] for payload in payloads if payload != "[DONE]"]
    assert {"role": "assistant", "content": ""} not in deltas
    assert [delta["content"] for delta in deltas[:3]] == ["ab", "cd", "ef"]
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[-1] == "[DONE]"


def test_completion_stream_events_can_reuse_completion_id():
    completion = {
        "created": 123,
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": "abc"}}],
    }

    payloads = []
    for event in _completion_to_stream_events(completion, chunk_id="chatcmpl-fixed"):
        for line in event.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                payloads.append(json.loads(line.removeprefix("data: ")))

    assert {payload["id"] for payload in payloads} == {"chatcmpl-fixed"}


def test_anthropic_streaming_tool_use_is_forwarded_as_openai_tool_call():
    start = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "read_file",
            "input": {},
        },
    }
    delta = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": "{\"path\""},
    }
    stop = {"type": "message_stop"}

    start_payload = json.loads(_anthropic_to_openai_chunk("test-model", start))
    tool_delta = start_payload["choices"][0]["delta"]["tool_calls"][0]
    assert tool_delta["id"] == "toolu_1"
    assert tool_delta["function"]["name"] == "read_file"
    assert tool_delta["function"]["arguments"] == ""

    delta_payload = json.loads(_anthropic_to_openai_chunk("test-model", delta))
    arg_delta = delta_payload["choices"][0]["delta"]["tool_calls"][0]
    assert arg_delta["index"] == 0
    assert arg_delta["function"]["arguments"] == "{\"path\""

    stop_payload = json.loads(
        _anthropic_to_openai_chunk("test-model", stop, finish_reason_override="tool_calls")
    )
    assert stop_payload["choices"][0]["finish_reason"] == "tool_calls"


def test_anthropic_completion_maps_max_tokens_to_length():
    completion = _anthropic_to_openai_completion(
        "test-model",
        {
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "partial"}],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    )

    assert completion["choices"][0]["finish_reason"] == "length"
    assert completion["usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }


def test_anthropic_completion_preserves_reported_cache_usage():
    completion = _anthropic_to_openai_completion(
        "test-model",
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "done"}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_input_tokens": 700,
                "cache_creation_input_tokens": 300,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100,
                    "ephemeral_1h_input_tokens": 200,
                },
            },
        },
    )

    assert completion["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": 700},
        "cache_read_input_tokens": 700,
        "cache_creation_input_tokens": 300,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 100,
            "ephemeral_1h_input_tokens": 200,
        },
        "uncached_input_tokens": 10,
        "cache_input_tokens": 1010,
    }


def test_cache_usage_summary_sums_split_creation_ttls_without_total():
    summary = _cache_usage_summary(
        {
            "claude_cache_creation_5_m_tokens": 100,
            "claude_cache_creation_1_h_tokens": 200,
        }
    )

    assert summary["cache_creation_input_tokens"] == 300
    assert summary["cache_creation"] == {
        "ephemeral_5m_input_tokens": 100,
        "ephemeral_1h_input_tokens": 200,
    }
    assert summary["write"] is True
    assert summary["read_reported"] is False
    assert summary["write_reported"] is True
    assert summary["reported"] is True


def test_cache_usage_summary_distinguishes_reported_zero_from_unknown():
    reported_zero = _cache_usage_summary(
        {
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
    )
    unknown = _cache_usage_summary({"prompt_tokens": 12})

    assert reported_zero["hit"] is False
    assert reported_zero["write"] is False
    assert reported_zero["read_reported"] is True
    assert reported_zero["write_reported"] is True
    assert reported_zero["reported"] is True
    assert reported_zero["input_tokens"] == 0
    assert reported_zero["input_reported"] is False
    assert reported_zero["cache_read_percent"] is None
    assert unknown["read_reported"] is False
    assert unknown["write_reported"] is False
    assert unknown["reported"] is False


def test_cache_usage_summary_calculates_read_share_only_with_reliable_input_total():
    anthropic = _cache_usage_summary(
        {
            "prompt_tokens": 10,
            "cache_read_input_tokens": 700,
            "cache_creation_input_tokens": 300,
            "cache_input_tokens": 1010,
        }
    )
    openai = _cache_usage_summary(
        {
            "prompt_tokens": 1000,
            "prompt_tokens_details": {"cached_tokens": 700},
        }
    )
    ambiguous = _cache_usage_summary(
        {
            "input_tokens": 10,
            "cache_read_input_tokens": 700,
            "cache_creation_input_tokens": 300,
        }
    )

    assert anthropic["cache_read_percent"] == 69.3
    assert anthropic["cache_prefix_reuse_percent"] == 70.0
    assert openai["cache_read_percent"] == 70.0
    assert openai["cache_prefix_reuse_percent"] == 100.0
    assert ambiguous["cache_read_percent"] is None
    assert ambiguous["cache_prefix_reuse_percent"] == 70.0


def test_openai_to_anthropic_unwraps_double_encoded_tool_arguments():
    double_encoded = json.dumps(
        json.dumps({"path": "notes.txt"}, ensure_ascii=False),
        ensure_ascii=False,
    )

    _system, messages = _openai_to_anthropic(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": double_encoded},
                    }
                ],
            }
        ]
    )

    tool_block = messages[0]["content"][0]
    assert tool_block["type"] == "tool_use"
    assert tool_block["name"] == "read_file"
    assert tool_block["input"] == {"path": "notes.txt"}


def test_anthropic_completion_unwraps_string_tool_input():
    completion = _anthropic_to_openai_completion(
        "test-model",
        {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": "{\"path\":\"notes.txt\"}",
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    )

    tool_call = completion["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["function"]["name"] == "read_file"
    assert json.loads(tool_call["function"]["arguments"]) == {"path": "notes.txt"}


def test_anthropic_stream_chunk_uses_supplied_id_and_length_finish_reason():
    stop = {"type": "message_stop"}

    payload = json.loads(
        _anthropic_to_openai_chunk(
            "test-model",
            stop,
            finish_reason_override="length",
            chunk_id="chatcmpl-fixed",
            created=123,
        )
    )

    assert payload["id"] == "chatcmpl-fixed"
    assert payload["created"] == 123
    assert payload["choices"][0]["finish_reason"] == "length"


def test_anthropic_tool_block_index_can_be_overridden_for_openai_tool_index():
    start = {
        "type": "content_block_start",
        "index": 2,
        "content_block": {
            "type": "tool_use",
            "id": "toolu_2",
            "name": "read_file",
            "input": {},
        },
    }
    delta = {
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "input_json_delta", "partial_json": "{\"path\""},
    }

    start_payload = json.loads(_anthropic_to_openai_chunk("test-model", start, tool_index_override=0))
    delta_payload = json.loads(_anthropic_to_openai_chunk("test-model", delta, tool_index_override=0))

    assert start_payload["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert delta_payload["choices"][0]["delta"]["tool_calls"][0]["index"] == 0


def test_anthropic_mixed_text_and_tool_stream_uses_compact_tool_indexes():
    state: dict[int, int] = {}
    text_start = {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}
    first_tool = {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"},
    }
    first_delta = {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": "{\"path\""},
    }
    second_tool = {
        "type": "content_block_start",
        "index": 3,
        "content_block": {"type": "tool_use", "id": "toolu_2", "name": "grep_code"},
    }

    assert _anthropic_tool_index_override(text_start, state) is None
    first_payload = json.loads(
        _anthropic_to_openai_chunk(
            "test-model",
            first_tool,
            tool_index_override=_anthropic_tool_index_override(first_tool, state),
        )
    )
    delta_payload = json.loads(
        _anthropic_to_openai_chunk(
            "test-model",
            first_delta,
            tool_index_override=_anthropic_tool_index_override(first_delta, state),
        )
    )
    second_payload = json.loads(
        _anthropic_to_openai_chunk(
            "test-model",
            second_tool,
            tool_index_override=_anthropic_tool_index_override(second_tool, state),
        )
    )

    assert first_payload["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert delta_payload["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert second_payload["choices"][0]["delta"]["tool_calls"][0]["index"] == 1
