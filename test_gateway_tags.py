from __future__ import annotations

from shenyu_gateway.response_capture import AssistantTagFilter, split_private_assistant_tags


def test_split_private_tags_with_both_blocks():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        'hello <heartbeat>secret</heartbeat> and [mem source="x"]remember this[/mem] world'
    )

    assert clean == "hello  and  world"
    assert heartbeat == "secret"
    assert len(memories) == 1
    assert memories[0]["content"] == "remember this"
    assert memories[0]["attrs"]["source"] == "x"
    assert stars == []


def test_split_private_tags_reverse_order():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        '[mem source="x"]remember this[/mem] then <heartbeat>secret</heartbeat> end'
    )

    assert clean == " then  end"
    assert heartbeat == "secret"
    assert len(memories) == 1
    assert memories[0]["content"] == "remember this"
    assert stars == []


def test_streaming_split_private_tags():
    tag_filter = AssistantTagFilter()
    parts = [
        "hello <heartbeat>",
        "secret</heartbeat> and [mem source=\"x\"]remember this",
        "[/mem] world",
    ]

    visible = "".join(tag_filter.feed(part) for part in parts) + tag_filter.flush()

    assert visible == "hello  and  world"
    assert tag_filter.get_heartbeat() == "secret"
    assert [item["content"] for item in tag_filter.get_memories()] == ["remember this"]
    assert tag_filter.get_stars() == []
