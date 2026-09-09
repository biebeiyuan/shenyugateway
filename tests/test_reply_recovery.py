from shenyu_gateway.gateway_admin_routes import collect_reply_recovery_rows


def test_collect_reply_recovery_rows_returns_latest_same_user_roll_group_only():
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
    assert [item["reply_version_id"] for item in result["replies"]] == ["v1", "v2"]
    assert result["replies"][1]["tool_rows"][0]["id"] == "t2"


def test_collect_reply_recovery_rows_stops_at_different_user_turn():
    rows = [
        {"role": "user", "content": "同一句"},
        {"role": "assistant", "content": "不应返回", "source_id": "old"},
        {"role": "user", "content": "别的问题"},
        {"role": "assistant", "content": "新回答", "source_id": "new"},
    ]
    result = collect_reply_recovery_rows(rows)
    assert [item["reply_version_id"] for item in result["replies"]] == ["new"]
