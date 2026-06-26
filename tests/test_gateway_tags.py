from __future__ import annotations

from shenyu_gateway.response_capture import AssistantTagFilter, split_private_assistant_tags


def test_split_private_tags_heartbeat_only():
    clean, heartbeat = split_private_assistant_tags(
        'hello <heartbeat>secret</heartbeat> world'
    )

    assert clean == "hello  world"
    assert heartbeat == "secret"


def test_split_private_tags_inline_mem_left_visible():
    clean, heartbeat = split_private_assistant_tags(
        '[mem source="x"]remember this[/mem] then <heartbeat>secret</heartbeat> end'
    )

    assert "[mem" in clean
    assert heartbeat == "secret"


def test_streaming_heartbeat_capture():
    tag_filter = AssistantTagFilter()
    parts = [
        "hello <heartbeat>",
        "secret</heartbeat> and world",
    ]

    visible = "".join(tag_filter.feed(part) for part in parts) + tag_filter.flush()

    assert visible == "hello  and world"
    assert tag_filter.get_heartbeat() == "secret"
