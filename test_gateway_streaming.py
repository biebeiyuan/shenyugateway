from __future__ import annotations

import json

import gateway


def _data_payload(event: str) -> dict:
    line = next(line for line in event.splitlines() if line.startswith("data: "))
    return json.loads(line.removeprefix("data: "))


def test_internal_tool_keepalive_is_openai_compatible_empty_delta():
    payload = _data_payload(gateway._stream_keepalive_event("test-model"))

    assert payload["object"] == "chat.completion.chunk"
    assert payload["model"] == "test-model"
    choice = payload["choices"][0]
    assert choice["delta"] == {"content": ""}
    assert choice["finish_reason"] is None


def test_stream_content_event_is_complete_openai_chunk():
    payload = _data_payload(
        gateway._stream_content_event(
            "test-model",
            "hello",
            chunk_id="chatcmpl-fixed",
            created=123,
        )
    )

    assert payload["id"] == "chatcmpl-fixed"
    assert payload["object"] == "chat.completion.chunk"
    assert payload["created"] == 123
    assert payload["model"] == "test-model"
    assert payload["choices"] == [
        {"index": 0, "delta": {"content": "hello"}, "finish_reason": None}
    ]


def test_sse_response_disables_proxy_buffering():
    async def generate():
        yield "data: [DONE]\n\n"

    response = gateway._sse_response(generate())

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


def test_record_response_text_keeps_full_detail_when_payloads_retained():
    entry = {"request_payloads_retained": True}
    gateway._record_response_text(entry, "x" * 250)

    assert entry["response_preview"].endswith("...")
    assert len(entry["response_preview"]) == 200
    assert entry["response_full"] == "x" * 250


def test_openai_stream_accumulator_collects_content_and_tool_arguments():
    completion = gateway._new_stream_completion("test-model")

    gateway._apply_openai_stream_chunk(
        completion,
        {"choices": [{"delta": {"content": "hello "}, "finish_reason": None}]},
    )
    gateway._apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
    )
    gateway._apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ":\"a.txt\"}"}}]},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 3},
        },
    )

    message = completion["choices"][0]["message"]
    assert message["content"] == "hello "
    assert message["tool_calls"][0]["function"]["name"] == "read_file"
    assert message["tool_calls"][0]["function"]["arguments"] == "{\"path\":\"a.txt\"}"
    assert completion["choices"][0]["finish_reason"] == "tool_calls"
    assert completion["usage"] == {"prompt_tokens": 3}


def test_openai_stream_accumulator_treats_null_arguments_as_empty_delta():
    completion = gateway._new_stream_completion("test-model")

    gateway._apply_openai_stream_chunk(
        completion,
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": None},
                            }
                        ]
                    }
                }
            ]
        },
    )
    gateway._apply_openai_stream_chunk(
        completion,
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"path\":\"a.txt\"}"}}]}}]},
    )

    arguments = completion["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert arguments == "{\"path\":\"a.txt\"}"


def test_stream_role_and_final_events_are_openai_compatible():
    role_payload = _data_payload(gateway._stream_role_event("test-model", chunk_id="chatcmpl-fixed", created=123))
    final_payload = _data_payload(
        gateway._stream_final_event("test-model", "tool_calls", chunk_id="chatcmpl-fixed", created=123)
    )

    assert role_payload["id"] == final_payload["id"] == "chatcmpl-fixed"
    assert role_payload["created"] == final_payload["created"] == 123
    assert role_payload["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert role_payload["choices"][0]["finish_reason"] is None
    assert final_payload["choices"][0]["delta"] == {}
    assert final_payload["choices"][0]["finish_reason"] == "tool_calls"


def test_anthropic_tool_block_indexes_are_compacted_for_openai():
    state: dict[int, int] = {}

    text_start = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    tool_start = {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use"}}
    tool_delta = {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta"}}
    second_tool = {"type": "content_block_start", "index": 3, "content_block": {"type": "tool_use"}}

    assert gateway._anthropic_tool_index_override(text_start, state) is None
    assert gateway._anthropic_tool_index_override(tool_start, state) == 0
    assert gateway._anthropic_tool_index_override(tool_delta, state) == 0
    assert gateway._anthropic_tool_index_override(second_tool, state) == 1


def test_completion_replay_skips_already_streamed_text_for_mixed_tools():
    completion = {
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I will check.\n\n<gateway_tool_results>\n[]\n</gateway_tool_results>",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                }
            }
        ],
    }

    replay = gateway._completion_with_unstreamed_deltas(
        completion,
        streamed_content="I will check.",
    )

    message = replay["choices"][0]["message"]
    assert message["content"] == "\n\n<gateway_tool_results>\n[]\n</gateway_tool_results>"
    assert completion["choices"][0]["message"]["content"].startswith("I will check.")
