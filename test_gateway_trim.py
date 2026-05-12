from __future__ import annotations

import ast
from pathlib import Path


def _load_trim_helpers():
    source = Path(__file__).with_name("gateway.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    wanted = {"_tool_call_ids", "_tool_safe_trim_start"}
    namespace: dict[str, object] = {}
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            block = ast.get_source_segment(source, node)
            exec(block, namespace)
    if not wanted.issubset(namespace):
        missing = wanted - set(namespace)
        raise RuntimeError(f"Missing helpers: {missing}")
    return namespace["_tool_safe_trim_start"]


_tool_safe_trim_start = _load_trim_helpers()


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
