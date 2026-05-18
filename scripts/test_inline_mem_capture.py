"""Regression checks for explicit inline [mem] capture."""

import ast
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shenyu_gateway.response_capture import split_private_assistant_tags


class Request:
    pass


def _iso_now():
    return "2026-05-10T00:00:00+00:00"


def load_gateway_symbols():
    source = Path(__file__).resolve().parents[1] / "gateway.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    wanted = {"AtomicMemoryService"}
    selected = [node for node in module.body if getattr(node, "name", None) in wanted]
    namespace = {
        "Any": Any,
        "Optional": Optional,
        "Request": Request,
        "_iso_now": _iso_now,
        "re": re,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


gateway_symbols = load_gateway_symbols()
AtomicMemoryService = gateway_symbols["AtomicMemoryService"]


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main():
    clean, _heartbeat, memories = split_private_assistant_tags("午安\n[mem]…[/mem]\n继续")
    assert_equal(clean, "午安\n\n继续", "punctuation-only mem tag body is hidden from visible text")
    assert_equal(memories, [], "punctuation-only mem is not captured")

    clean, _heartbeat, memories = split_private_assistant_tags("a\n[mem]   [/mem]\nb")
    assert_equal(clean, "a\n\nb", "blank mem tag body is hidden from visible text")
    assert_equal(memories, [], "blank mem is not captured")

    clean, _heartbeat, memories = split_private_assistant_tags("a\n[mem]她今天想早睡[/mem]\nb")
    assert_equal(clean, "a\n\nb", "valid mem tag body is hidden from visible text")
    assert_equal(memories, [{"content": "她今天想早睡", "attrs": {}}], "valid mem is captured")

    service = AtomicMemoryService(request=None)
    row = service._inline_note_to_active_memory(
        memories[0],
        {"id": "session-id", "session_tag": "default"},
        "test-model",
    )
    assert row is not None
    assert_equal(row["subject"], "沈予", "default subject")
    assert_equal(row["owner"], "assistant", "default owner")
    for legacy_field in ("content_canonical", "valence", "arousal", "confidence"):
        if legacy_field in row:
            raise AssertionError(f"legacy field still written: {legacy_field}")

    assert service._inline_note_to_active_memory(
        {"content": "主动标我们", "attrs": {"subject": "我们"}},
        {"id": "session-id", "session_tag": "default"},
        "test-model",
    )["subject"] == "我们"

    print("inline mem capture regression checks passed")


if __name__ == "__main__":
    main()
