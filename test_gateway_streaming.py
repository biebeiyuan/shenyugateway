from __future__ import annotations

import asyncio
import json
import tempfile

import gateway
from shenyu_gateway.sessions import SessionManager
from shenyu_gateway.store import GatewayStore


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
                    "content": "I will check.\n\n第一段正文。\n\n第二段正文。",
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
    assert message["content"] == "\n\n第一段正文。\n\n第二段正文。"
    assert completion["choices"][0]["message"]["content"].startswith("I will check.")


def test_pending_gateway_tool_turn_store_round_trip_consume_and_prune():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        pending = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_client"],
            original_assistant_message={"role": "assistant", "tool_calls": [{"id": "call_client"}]},
            gateway_tool_messages=[{"role": "tool", "tool_call_id": "call_gateway", "content": "{\"ok\":true}"}],
        )

        found = store.find_pending_gateway_tool_turn(session["id"], ["call_client"])

        assert found is not None
        assert found["id"] == pending["id"]
        assert found["client_tool_call_ids"] == ["call_client"]
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_other"]) is None
        assert store.mark_pending_gateway_tool_turns_consumed([pending["id"]]) == 1
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"]) is None
        assert store.prune_pending_gateway_tool_turns(session["id"]) == 1

        expired = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_expired"],
            original_assistant_message={"role": "assistant", "tool_calls": [{"id": "call_expired"}]},
            gateway_tool_messages=[],
            ttl_minutes=-1,
        )
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_expired"]) is None
        assert store.prune_pending_gateway_tool_turns(session["id"]) >= 1
        assert expired["id"]


def test_pending_gateway_tool_turn_lookup_uses_canonical_tool_ids():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        target = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_b", "call_a"],
            original_assistant_message={"role": "assistant", "tool_calls": []},
            gateway_tool_messages=[],
        )
        for index in range(30):
            store.create_pending_gateway_tool_turn(
                session_id=session["id"],
                session_tag=session["session_tag"],
                client_tool_call_ids=[f"call_other_{index}"],
                original_assistant_message={"role": "assistant", "tool_calls": []},
                gateway_tool_messages=[],
            )

        found = store.find_pending_gateway_tool_turn(session["id"], ["call_a", "call_b"])

        assert target["client_tool_call_ids"] == ["call_a", "call_b"]
        assert found is not None
        assert found["id"] == target["id"]


def test_pending_gateway_tool_turn_rebuilds_mixed_transcript_before_upstream():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(f"{tmp}/gateway.db")
        session = store.get_or_create_session("test-session", "test-client")
        original_assistant = {
            "role": "assistant",
            "content": "I will check both.",
            "tool_calls": [
                {
                    "id": "call_gateway",
                    "type": "function",
                    "function": {"name": "shenyu_recall", "arguments": "{}"},
                },
                {
                    "id": "call_client",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                },
            ],
        }
        gateway_result = {
            "role": "tool",
            "tool_call_id": "call_gateway",
            "name": "shenyu_recall",
            "content": "{\"ok\":true}",
        }
        pending = store.create_pending_gateway_tool_turn(
            session_id=session["id"],
            session_tag=session["session_tag"],
            client_tool_call_ids=["call_client"],
            original_assistant_message=original_assistant,
            gateway_tool_messages=[gateway_result],
        )
        client_messages = [
            {"role": "user", "content": "check"},
            {
                "role": "assistant",
                "content": "I will check both.",
                "tool_calls": [original_assistant["tool_calls"][1]],
            },
            {"role": "tool", "tool_call_id": "call_client", "name": "read_file", "content": "file body"},
        ]

        rebuilt, meta = gateway._inject_pending_gateway_tool_turns(
            client_messages,
            store,
            session["id"],
        )

        assert meta["pending_gateway_tool_turns_injected"] == 1
        assert meta["pending_gateway_tool_turn_ids"] == [pending["id"]]
        assert rebuilt == [
            client_messages[0],
            original_assistant,
            gateway_result,
            client_messages[2],
        ]
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"]) is not None
        assert store.mark_pending_gateway_tool_turns_consumed(meta["pending_gateway_tool_turn_ids"]) == 1
        assert store.find_pending_gateway_tool_turn(session["id"], ["call_client"]) is None


def test_execute_mixed_gateway_tool_calls_stores_hidden_result_and_returns_only_client_calls():
    async def run_case():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(f"{tmp}/gateway.db")
            session = store.get_or_create_session("test-session", "test-client")
            sessions = SessionManager(store, gateway.cfg)
            old_store = gateway.session_store
            old_execute = gateway.execute_gateway_tool

            async def fake_execute(name, args, session_tag=None, cfg=None):
                return {"ok": True, "items": [{"content": "hidden gateway result", "source_table": "journal"}]}

            gateway.session_store = store
            gateway.execute_gateway_tool = fake_execute
            try:
                completion = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 123,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "I will check.",
                                "tool_calls": [
                                    {
                                        "id": "call_gateway",
                                        "type": "function",
                                        "function": {"name": "shenyu_recall", "arguments": "{\"q\":\"x\"}"},
                                    },
                                    {
                                        "id": "call_client",
                                        "type": "function",
                                        "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
                                    },
                                ],
                            },
                        }
                    ],
                }

                result, gateway_calls, client_calls = await gateway._execute_mixed_gateway_tool_calls(
                    completion,
                    completion["choices"][0]["message"]["tool_calls"],
                    session["session_tag"],
                    sessions,
                    session["id"],
                )
            finally:
                gateway.session_store = old_store
                gateway.execute_gateway_tool = old_execute

            message = result["choices"][0]["message"]
            pending = store.find_pending_gateway_tool_turn(session["id"], ["call_client"])
            replay_events = list(
                gateway._completion_to_stream_events(
                    result,
                    include_role=False,
                    content_chunk_chars=1200,
                    chunk_id="chatcmpl-fixed",
                )
            )
            response_text = json.dumps(result, ensure_ascii=False) + "\n".join(replay_events)

            assert [gateway._tool_call_name(call) for call in gateway_calls] == ["shenyu_recall"]
            assert [gateway._tool_call_name(call) for call in client_calls] == ["read_file"]
            assert [gateway._tool_call_name(call) for call in message["tool_calls"]] == ["read_file"]
            assert message["content"] == "I will check."
            assert pending is not None
            assert "hidden gateway result" in pending["gateway_tool_messages"][0]["content"]
            assert "hidden gateway result" not in response_text
            assert "<gateway_tool_results>" not in response_text

    asyncio.run(run_case())


def test_execute_mixed_gateway_tool_calls_stores_clean_pending_assistant_copy():
    async def run_case():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(f"{tmp}/gateway.db")
            session = store.get_or_create_session("test-session", "test-client")
            sessions = SessionManager(store, gateway.cfg)
            old_store = gateway.session_store
            old_execute = gateway.execute_gateway_tool

            async def fake_execute(name, args, session_tag=None, cfg=None):
                return {"ok": True}

            gateway.session_store = store
            gateway.execute_gateway_tool = fake_execute
            try:
                completion = {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Visible [mem]private note[/mem]",
                                "tool_calls": [
                                    {
                                        "id": "call_gateway",
                                        "type": "function",
                                        "function": {"name": "shenyu_recall", "arguments": "{}"},
                                    },
                                    {
                                        "id": "call_client",
                                        "type": "function",
                                        "function": {"name": "read_file", "arguments": "{}"},
                                    },
                                ],
                            }
                        }
                    ]
                }

                result, _, _ = await gateway._execute_mixed_gateway_tool_calls(
                    completion,
                    completion["choices"][0]["message"]["tool_calls"],
                    session["session_tag"],
                    sessions,
                    session["id"],
                )
            finally:
                gateway.session_store = old_store
                gateway.execute_gateway_tool = old_execute

            pending = store.find_pending_gateway_tool_turn(session["id"], ["call_client"])

            assert pending is not None
            assert pending["original_assistant_message"].get("content", "").strip() == "Visible"
            assert "[mem]" not in pending["original_assistant_message"].get("content", "")
            assert result["choices"][0]["message"]["content"] == "Visible [mem]private note[/mem]"

    asyncio.run(run_case())
