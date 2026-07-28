from __future__ import annotations

import json

from shenyu_gateway.upstream_response_evidence import (
    UPSTREAM_RESPONSE_EVIDENCE_KEY,
    ensure_upstream_response_evidence,
    observe_normalized_completion,
    observe_normalized_stream_chunk,
    observe_upstream_nonstream_response,
    observe_upstream_stream_event,
    upstream_response_evidence_snapshot,
)


def test_anthropic_nonstream_evidence_counts_shapes_without_content():
    upstream = {"protocol": "anthropic"}
    evidence = ensure_upstream_response_evidence(
        upstream,
        {"thinking": {"type": "adaptive", "display": "summarized"}},
        "nonstream",
    )
    observe_upstream_nonstream_response(
        evidence,
        {
            "content": [
                {"type": "thinking", "thinking": "private summary", "signature": "opaque"},
                {"type": "redacted_thinking", "data": "opaque redaction"},
                {"type": "text", "text": "visible answer"},
                {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {}},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 4},
            "stop_reason": "tool_use",
        },
    )
    observe_normalized_completion(
        evidence,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "visible answer",
                        "reasoning_content": "private summary",
                        "tool_calls": [{"id": "tool-1", "type": "function", "function": {}}],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        },
    )

    snapshot = upstream_response_evidence_snapshot(upstream)
    assert snapshot is not None
    assert snapshot["thinking_requested"] is True
    assert snapshot["upstream_format"] == "anthropic_message"
    assert snapshot["upstream"]["thinking_blocks"] == 1
    assert snapshot["upstream"]["redacted_thinking_blocks"] == 1
    assert snapshot["upstream"]["thinking_content_seen"] is True
    assert snapshot["upstream"]["usage_values_seen"] is True
    assert snapshot["upstream"]["finish_seen"] is True
    assert snapshot["normalized"]["thinking_blocks"] == 1
    assert snapshot["normalized"]["thinking_content_seen"] is True
    serialized = json.dumps(snapshot)
    assert "private summary" not in serialized
    assert "opaque" not in serialized
    assert "visible answer" not in serialized


def test_anthropic_stream_evidence_counts_thinking_signature_usage_and_finish():
    upstream = {"protocol": "anthropic"}
    evidence = ensure_upstream_response_evidence(
        upstream,
        {"thinking": {"type": "enabled"}},
        "stream",
    )
    for event in [
        {"type": "message_start", "message": {"usage": {"input_tokens": 8}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "hidden"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "opaque"},
        },
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ]:
        observe_upstream_stream_event(evidence, event)
    observe_normalized_stream_chunk(
        evidence,
        {"choices": [{"delta": {"reasoning_content": "hidden"}, "finish_reason": None}]},
    )

    assert evidence["upstream_format"] == "anthropic_events"
    assert evidence["upstream"]["events"] == 6
    assert evidence["upstream"]["thinking_blocks"] == 1
    assert evidence["upstream"]["thinking_deltas"] == 1
    assert evidence["upstream"]["signature_deltas"] == 1
    assert evidence["upstream"]["thinking_content_seen"] is True
    assert evidence["upstream"]["usage_seen"] is True
    assert evidence["upstream"]["finish_seen"] is True
    assert evidence["normalized"]["thinking_deltas"] == 1
    assert evidence["normalized"]["thinking_content_seen"] is True


def test_openai_evidence_marks_nonstandard_message_fields_without_names_or_values():
    upstream = {"protocol": "openai"}
    evidence = ensure_upstream_response_evidence(
        upstream,
        {"reasoning_effort": "high"},
        "nonstream",
    )
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "reasoning",
                    "relay_private_metadata": "must not persist",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {},
    }
    observe_upstream_nonstream_response(evidence, response)
    observe_normalized_completion(evidence, response)

    assert evidence["upstream_format"] == "openai_completion"
    assert evidence["upstream"]["thinking_blocks"] == 1
    assert evidence["upstream"]["other_fields"] == 1
    assert evidence["upstream"]["usage_seen"] is True
    assert evidence["upstream"]["usage_values_seen"] is False
    assert "relay_private_metadata" not in json.dumps(evidence)
    assert "must not persist" not in json.dumps(evidence)


def test_snapshot_is_detached_and_private_storage_key_is_not_part_of_evidence():
    upstream = {"protocol": "openai"}
    ensure_upstream_response_evidence(upstream, {}, "stream")

    snapshot = upstream_response_evidence_snapshot(upstream)
    assert snapshot is not None
    snapshot["upstream"]["events"] = 99

    assert upstream[UPSTREAM_RESPONSE_EVIDENCE_KEY]["upstream"]["events"] == 0
    assert UPSTREAM_RESPONSE_EVIDENCE_KEY not in snapshot


def test_reset_starts_each_upstream_round_with_fresh_counters():
    upstream = {"protocol": "openai"}
    first = ensure_upstream_response_evidence(upstream, {}, "stream", reset=True)
    observe_upstream_stream_event(
        first,
        {"choices": [{"delta": {"content": "first"}, "finish_reason": "stop"}]},
    )

    second = ensure_upstream_response_evidence(upstream, {}, "stream", reset=True)

    assert second is not first
    assert second["upstream"]["events"] == 0
    assert second["upstream"]["text_deltas"] == 0
