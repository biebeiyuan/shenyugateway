from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def _load_assistant_tag_filter():
    source = Path(__file__).with_name("gateway.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "_AssistantTagFilter":
            block = ast.get_source_segment(source, node)
            namespace = {"re": re, "Any": Any}
            exec(block, namespace)
            return namespace["_AssistantTagFilter"]
    raise RuntimeError("_AssistantTagFilter not found")


_AssistantTagFilter = _load_assistant_tag_filter()


def _split_private_assistant_tags(content: str):
    tag_filter = _AssistantTagFilter()
    clean_content = tag_filter.feed(content or "") + tag_filter.flush()
    return clean_content, tag_filter.get_heartbeat(), tag_filter.get_memories()


def test_split_private_tags_with_both_blocks():
    clean, heartbeat, memories = _split_private_assistant_tags(
        'hello <heartbeat>secret</heartbeat> and [mem source="x"]remember this[/mem] world'
    )

    assert clean == "hello  and  world"
    assert heartbeat == "secret"
    assert len(memories) == 1
    assert memories[0]["content"] == "remember this"
    assert memories[0]["attrs"]["source"] == "x"


def test_split_private_tags_reverse_order():
    clean, heartbeat, memories = _split_private_assistant_tags(
        '[mem source="x"]remember this[/mem] then <heartbeat>secret</heartbeat> end'
    )

    assert clean == " then  end"
    assert heartbeat == "secret"
    assert len(memories) == 1
    assert memories[0]["content"] == "remember this"


def test_streaming_split_private_tags():
    tag_filter = _AssistantTagFilter()
    parts = [
        "hello <heartbeat>",
        "secret</heartbeat> and [mem source=\"x\"]remember this",
        "[/mem] world",
    ]

    visible = "".join(tag_filter.feed(part) for part in parts) + tag_filter.flush()

    assert visible == "hello  and  world"
    assert tag_filter.get_heartbeat() == "secret"
    assert [item["content"] for item in tag_filter.get_memories()] == ["remember this"]
