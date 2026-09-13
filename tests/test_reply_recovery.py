from shenyu_gateway.gateway_admin_routes import collect_reply_recovery_rows
from shenyu_gateway.tool_loop import _visible_round_content


def test_collect_reply_recovery_rows_returns_latest_request_only():
    rows = [
        {"id": "u0", "role": "user", "content": "旧问题"},
        {"id": "a0", "role": "assistant", "content": "旧回答", "source_id": "old"},
        {"id": "u1", "role": "user", "content": "想吃什么【10/09 周四 10:00 · 第1天】"},
        {"id": "a1", "role": "assistant", "content": "第一版", "source_id": "v1"},
        {"id": "u2", "role": "user", "content": "想吃什么【10/09 周四 10:01 · 第1天】"},
        {"id": "t2", "role": "tool", "tool_name": "shenyu_recall", "content": '{"ok":true}'},
        {"id": "a2", "role": "assistant", "content": "第二版", "source_id": "v2"},
        {"id": "u3", "role": "user", "content": "想吃什么【10/09 周四 10:02 · 第1天】"},
    ]
    result = collect_reply_recovery_rows(rows)
    assert result["user_content"].startswith("想吃什么")
    assert result["replies"] == []

    rows.append({"id": "a3", "role": "assistant", "content": "第三版", "source_id": "v3"})
    result = collect_reply_recovery_rows(rows)
    assert [item["reply_version_id"] for item in result["replies"]] == ["v3"]


def test_collect_reply_recovery_rows_stops_at_different_user_turn():
    rows = [
        {"role": "user", "content": "同一句"},
        {"role": "assistant", "content": "不应返回", "source_id": "old"},
        {"role": "user", "content": "别的问题"},
        {"role": "assistant", "content": "新回答", "source_id": "new"},
    ]
    result = collect_reply_recovery_rows(rows)
    assert [item["reply_version_id"] for item in result["replies"]] == ["new"]


def test_visible_round_content_removes_private_echo_and_tags():
    completion = {
        "choices": [{
            "message": {
                "content": "[回响]看着你[/回响]先查一下",
            },
        }],
    }
    assert _visible_round_content(completion) == "先查一下"
