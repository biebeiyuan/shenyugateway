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
    clean, heartbeat = split_private_assistant_tags(
        "可以用 [mem] 标签写。\n<heartbeat>心跳内容</heartbeat>"
    )

    assert "[mem] 标签写" in clean
    assert "heartbeat" not in clean.lower()
    assert heartbeat == "心跳内容"


def test_heartbeat_is_captured():
    clean, heartbeat = split_private_assistant_tags(
        "正文\n<heartbeat>心跳内容</heartbeat>"
    )

    assert clean.strip() == "正文"
    assert heartbeat == "心跳内容"


def test_multiple_heartbeats_are_captured():
    clean, heartbeat = split_private_assistant_tags(
        "正文<heartbeat>心跳1</heartbeat>中间<heartbeat>心跳2</heartbeat>结尾"
    )

    assert "正文" in clean
    assert "中间" in clean
    assert "结尾" in clean
    assert "心跳1" in heartbeat
    assert "心跳2" in heartbeat


def test_no_heartbeat_returns_empty():
    clean, heartbeat = split_private_assistant_tags("正文，没有私有块。")

    assert clean == "正文，没有私有块。"
    assert heartbeat == ""


def test_inline_mem_and_star_tags_are_left_visible():
    clean, heartbeat = split_private_assistant_tags(
        "正文[mem]便签内容[/mem]中间[star]星内容[/star]结尾"
    )

    assert "[mem]便签内容[/mem]" in clean
    assert "[star]星内容[/star]" in clean
    assert heartbeat == ""


def test_private_capture_fallback_does_not_claim_async_storage_completed():
    text, context = private_capture_fallback_text("", ["heartbeat", "star"])

    assert context == "generic"
    assert text == "沈予已记录 · 已记录私有块 heartbeat + star"
