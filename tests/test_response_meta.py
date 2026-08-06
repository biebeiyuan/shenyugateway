from types import SimpleNamespace

from shenyu_gateway.response_meta import (
    attach_response_meta,
    build_response_meta,
    response_meta_enabled,
)
from shenyu_gateway.tool_loop import _tool_response_meta


def test_build_response_meta_maps_context_cache_tool_and_heartbeat_status():
    meta = build_response_meta(
        {
            "client_message_window": {
                "human_turn_groups_retained": 84,
                "client_non_system_retained": 167,
                "context_high_water": 200,
            }
        },
        {
            "cache_read_percent": 68.35,
            "cache_read_input_tokens": 700,
            "total_input_tokens": 1024,
        },
        heartbeat_captured=True,
        tool_rounds=2,
        first_tool_round_cache_hit=True,
    )

    assert meta == {
        "context_rounds": 84,
        "context_trim_in_rounds": 17,
        "cache_read_percent": 68.3,
        "cache_read_input_tokens": 700,
        "cache_total_input_tokens": 1024,
        "tool_rounds": 2,
        "first_tool_round_cache_hit": True,
        "heartbeat_captured": True,
    }


def test_response_meta_is_only_enabled_for_the_explicit_client_profile():
    assert response_meta_enabled({"client_profile": {"emit_response_meta": True}}) is True
    assert response_meta_enabled({"client_profile": {"emit_tool_events": True}}) is False
    assert response_meta_enabled({}) is False


def test_attach_response_meta_keeps_existing_shenyu_fields_and_unknown_cache_rate():
    completion = {"shenyu": {"tool_events": [{"phase": "tool_start"}]}}

    attach_response_meta(
        completion,
        {"client_message_window": {"human_turn_groups_retained": 4}},
        {"cache_read_input_tokens": 120},
    )

    assert completion["shenyu"]["tool_events"] == [{"phase": "tool_start"}]
    assert completion["shenyu"]["response_meta"]["context_rounds"] == 4
    assert completion["shenyu"]["response_meta"]["cache_read_percent"] is None
    assert completion["shenyu"]["response_meta"]["first_tool_round_cache_hit"] is False


def test_context_trim_count_follows_dynamic_high_water_and_unlimited_mode():
    configured = build_response_meta(
        {
            "client_message_window": {
                "human_turn_groups_retained": 38,
                "client_non_system_retained": 75,
                "context_high_water": 95,
            }
        },
        {},
    )
    unlimited = build_response_meta(
        {
            "client_message_window": {
                "human_turn_groups_retained": 38,
                "client_non_system_retained": 75,
                "context_high_water": None,
            }
        },
        {},
    )

    assert configured["context_trim_in_rounds"] == 11
    assert unlimited["context_trim_in_rounds"] is None


def test_tool_response_meta_uses_aggregate_rate_and_marks_first_round_hit():
    ctx = SimpleNamespace(
        meta={
            "client_message_window": {
                "human_turn_groups_retained": 8,
            },
            "heartbeat_captured": False,
        },
        log_entry={
            "cache_usage": {
                "cache_read_percent": 72.5,
                "cache_read_input_tokens": 1450,
                "total_input_tokens": 2000,
            },
            "internal_tool_rounds": [
                {
                    "cache_usage": {"cache_read_input_tokens": 700},
                    "tools": [{"name": "shenyu_recall"}],
                },
                {
                    "cache_usage": {"cache_read_input_tokens": 750},
                    "tools": [],
                },
            ],
        },
    )

    meta = _tool_response_meta(ctx)

    assert meta["cache_read_percent"] == 72.5
    assert meta["tool_rounds"] == 1
    assert meta["first_tool_round_cache_hit"] is True
