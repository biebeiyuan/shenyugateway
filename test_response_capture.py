from __future__ import annotations

import sys
import types

if "dotenv" not in sys.modules:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv

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
