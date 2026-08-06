from __future__ import annotations

import json

import pytest

from shenyu_gateway.project_delivery import (
    ProjectDeliveryError,
    append_delivery,
    load_delivery_log,
    normalize_delivery,
)


def _delivery(**overrides):
    value = {
        "id": "delivery-one",
        "completed_at": "2026-08-06T10:18:33+08:00",
        "title": "PWA 新增请求头",
        "product": "PWA 聊天端",
        "kind": "feature",
        "summary": "增加可编辑请求头。",
        "touchpoint": "PWA 模型面板",
        "why": "上游兼容需要。",
        "status": "pushed",
        "verification": ["PWA test"],
        "paths": ["pwa/src/App.vue"],
        "docs": ["README.md"],
        "commit": "abc123",
        "lesson": "浏览器不能直接覆盖 User-Agent。",
        "debug_ref": "",
        "recorded_by": "Codex",
    }
    value.update(overrides)
    return value


def test_delivery_log_round_trip_is_sorted_and_normalized(tmp_path):
    path = tmp_path / "deliveries.jsonl"
    older = _delivery(id="older", completed_at="2026-08-05T12:00:00+08:00")
    newer = _delivery(id="newer", completed_at="2026-08-06T12:00:00+08:00")
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in [older, newer]) + "\n",
        encoding="utf-8",
    )

    deliveries = load_delivery_log(path)

    assert [item["id"] for item in deliveries] == ["newer", "older"]
    assert deliveries[0]["completed_at"] == "2026-08-06T12:00:00+08:00"
    assert deliveries[0]["verification"] == ["PWA test"]


def test_append_delivery_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "deliveries.jsonl"
    append_delivery(_delivery(), path)

    with pytest.raises(ProjectDeliveryError, match="duplicate id"):
        append_delivery(_delivery(), path)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"completed_at": "2026-08-06"}, "timezone"),
        ({"kind": "docs"}, "unsupported kind"),
        ({"status": "done"}, "unsupported status"),
        ({"verification": []}, "at least one item"),
        ({"paths": []}, "at least one item"),
    ],
)
def test_delivery_validation_rejects_ambiguous_records(overrides, message):
    with pytest.raises(ProjectDeliveryError, match=message):
        normalize_delivery(_delivery(**overrides))
