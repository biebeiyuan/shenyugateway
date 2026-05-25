from __future__ import annotations

import json

from shenyu_gateway.upstream_adapter import _completion_to_stream_events


def _stream_payloads(completion: dict):
    payloads = []
    for event in _completion_to_stream_events(completion):
        for line in event.splitlines():
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            payloads.append("[DONE]" if data == "[DONE]" else json.loads(data))
    return payloads


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
