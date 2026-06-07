from __future__ import annotations

from shenyu_gateway.calendar import extract_json_object


def test_extract_json_object_keeps_missing_summary_empty():
    parsed = extract_json_object('{"title":"日历记忆","content":"正文很长很长","digest":"短记忆"}')

    assert parsed["content"] == "正文很长很长"
    assert parsed["summary"] == ""
    assert parsed["digest"] == "短记忆"


def test_extract_json_object_does_not_derive_summary_from_raw_text():
    parsed = extract_json_object("这是一段没有 JSON 包裹的日历正文。")

    assert parsed["content"] == "这是一段没有 JSON 包裹的日历正文。"
    assert parsed["summary"] == ""
    assert parsed["digest"]
