from __future__ import annotations

from scripts.context_window_observer import summarize


def test_context_window_observer_summarizes_events_without_message_content():
    events = [
        {
            "session_id": "s1",
            "event_class": "new_user",
            "epoch_id": "e1",
            "created_at": "2026-07-10T02:00:00Z",
            "detail": {
                "context_epoch_reset": False,
                "client_non_system_retained": 170,
                "raw_tool_protection_turns": 18,
                "memory_island_decision": {"decision": "retained"},
            },
        },
        {
            "session_id": "s1",
            "event_class": "new_user",
            "epoch_id": "e2",
            "created_at": "2026-07-10T01:00:00Z",
            "detail": {
                "context_epoch_reset": True,
                "context_epoch_reset_reason": "message_high_water",
                "client_non_system_retained": 168,
                "raw_tool_protection_turns": 18,
                "memory_island_decision": {"decision": "rewritten"},
            },
        },
    ]

    result = summarize(events)

    assert result["events"] == 2
    assert result["epochs"] == 2
    assert result["event_classes"] == {"new_user": 2}
    assert result["epoch_resets"] == {"message_high_water": 1}
    assert result["memory_island_decisions"] == {"retained": 1, "rewritten": 1}
