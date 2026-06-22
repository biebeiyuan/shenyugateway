from __future__ import annotations

import sys
import types

if "dotenv" not in sys.modules:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv

from shenyu_gateway.private_capture import private_capture_fallback_text
from shenyu_gateway.response_capture import split_private_assistant_tags


def test_literal_unclosed_mem_does_not_block_heartbeat_capture():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "可以用 [mem] 标签写。\n<heartbeat>心跳内容</heartbeat>"
    )

    assert "[mem] 标签写" in clean
    assert "heartbeat" not in clean.lower()
    assert heartbeat == "心跳内容"
    assert memories == []
    assert stars == []


def test_closed_mem_and_heartbeat_are_captured_together():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "正文\n[mem]便签内容[/mem]\n<heartbeat>心跳内容</heartbeat>"
    )

    assert clean.strip() == "正文"
    assert heartbeat == "心跳内容"
    assert memories == [{"content": "便签内容", "attrs": {}}]
    assert stars == []


def test_nested_private_tags_are_split_instead_of_polluting_outer_capture():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "正文[mem]外层便签 [star]Bbmaj7 → Am(maj7) → F#m7 · 实体化一段[/star] 收尾[/mem]"
        "<heartbeat>心跳内容</heartbeat>"
    )

    assert clean.strip() == "正文"
    assert heartbeat == "心跳内容"
    assert memories == [{"content": "外层便签  收尾", "attrs": {}}]
    assert stars == [{"content": "Bbmaj7 → Am(maj7) → F#m7 · 实体化一段", "attrs": {}}]


def test_nested_same_tag_waits_for_matching_outer_close():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "[star]Bbmaj7 → Am(maj7) → F#m7 · 外层 [star]Cm(add9) · 内层[/star] 结尾[/star]"
    )

    assert clean == ""
    assert heartbeat == ""
    assert memories == []
    assert stars == [
        {"content": "Cm(add9) · 内层", "attrs": {}},
        {"content": "Bbmaj7 → Am(maj7) → F#m7 · 外层  结尾", "attrs": {}},
    ]


def test_heartbeat_nested_inside_star_is_split_out():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "[star]Cm(add9) · 星正文 <heartbeat>心跳内容</heartbeat> 收尾[/star]"
    )

    assert clean == ""
    assert heartbeat == "心跳内容"
    assert memories == []
    assert stars == [{"content": "Cm(add9) · 星正文  收尾", "attrs": {}}]


def test_literal_unclosed_mem_inside_star_does_not_block_star_capture():
    clean, heartbeat, memories, stars = split_private_assistant_tags(
        "[star]Cm(add9) · 星正文里只是提到 [mem] 字面标签，不是真的便签[/star]"
    )

    assert clean == ""
    assert heartbeat == ""
    assert memories == []
    assert stars == [{"content": "Cm(add9) · 星正文里只是提到 [mem] 字面标签，不是真的便签", "attrs": {}}]


def test_private_capture_fallback_does_not_claim_async_storage_completed():
    text, context = private_capture_fallback_text("", ["heartbeat", "star"])

    assert context == "generic"
    assert text == "沈予已记录 · 已记录私有块 heartbeat + star"
