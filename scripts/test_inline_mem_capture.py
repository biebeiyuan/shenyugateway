"""Regression checks for explicit inline [mem] capture."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shenyu_gateway.mem_notes import MemNoteService
from shenyu_gateway.response_capture import split_private_assistant_tags


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main():
    clean, _heartbeat, memories, _stars = split_private_assistant_tags("午安\n[mem]…[/mem]\n继续")
    assert_equal(clean, "午安\n\n继续", "punctuation-only mem tag body is hidden from visible text")
    assert_equal(memories, [], "punctuation-only mem is not captured")

    clean, _heartbeat, memories, _stars = split_private_assistant_tags("a\n[mem]   [/mem]\nb")
    assert_equal(clean, "a\n\nb", "blank mem tag body is hidden from visible text")
    assert_equal(memories, [], "blank mem is not captured")

    clean, _heartbeat, memories, _stars = split_private_assistant_tags("a\n[mem]她今天想早睡[/mem]\nb")
    assert_equal(clean, "a\n\nb", "valid mem tag body is hidden from visible text")
    assert_equal(memories, [{"content": "她今天想早睡", "attrs": {}}], "valid mem is captured")

    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), None)
    row = service._inline_note_to_row(
        memories[0],
        {"id": "session-id", "session_tag": "default"},
        "visible assistant text",
        "test-model",
    )
    assert row is not None
    assert_equal(row["content"], "她今天想早睡", "inline mem content")
    assert_equal(row["status"], "captured", "inline mem status")
    assert_equal(row["source_session_id"], "session-id", "source session")
    for legacy_field in ("content_canonical", "valence", "arousal", "confidence"):
        if legacy_field in row:
            raise AssertionError(f"legacy field still written: {legacy_field}")

    assert service._inline_note_to_row(
        {"content": "主动标我们", "attrs": {"subject": "我们"}},
        {"id": "session-id", "session_tag": "default"},
        "visible assistant text",
        "test-model",
    )["content"] == "主动标我们"

    print("inline mem capture regression checks passed")


if __name__ == "__main__":
    main()
