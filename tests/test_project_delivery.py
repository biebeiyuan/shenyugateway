from __future__ import annotations

import json
from pathlib import Path

import pytest

from shenyu_gateway.project_delivery import (
    ABANDONED_FIELD_WIDTH_LIMIT,
    ProjectDeliveryError,
    append_delivery,
    display_width,
    load_delivery_log,
    main,
    normalize_delivery,
    parse_abandoned_argument,
)

ROOT = Path(__file__).resolve().parent.parent


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


def test_abandoned_roads_are_optional_and_keep_their_three_fields():
    without = normalize_delivery(_delivery())
    assert without["abandoned"] == []

    record = normalize_delivery(
        _delivery(
            abandoned=[
                {
                    "what": "从 migrations 推导可用列",
                    "why": "9 张被查询的表里 3 张仓库没有迁移，推不成全仓不变量。",
                    "cost": "半小时探查",
                }
            ]
        )
    )

    assert record["abandoned"] == [
        {
            "what": "从 migrations 推导可用列",
            "why": "9 张被查询的表里 3 张仓库没有迁移，推不成全仓不变量。",
            "cost": "半小时探查",
        }
    ]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"what": "甲", "why": "乙"}, "cost is required"),
        ({"what": "甲", "why": "乙", "cost": ""}, "cost is required"),
        ({"what": "甲", "why": "乙", "cost": "半小时", "how": "先量后改"}, "unsupported field"),
        ({"what": "甲", "why": "第一步\n第二步", "cost": "半小时"}, "single line"),
        # 61 Chinese characters is 122 columns. Under the old character count the
        # same limit allowed 120 of them — a paragraph, which is what this field
        # was written to refuse.
        ({"what": "甲", "why": "乙" * 61, "cost": "半小时"}, "at most"),
        ({"what": "甲", "why": "b" * 121, "cost": "半小时"}, "at most"),
        ("放弃了缓存", "must be an object"),
    ],
)
def test_abandoned_format_is_locked_to_three_short_lines(entry, message):
    # The field exists so the next agent can skip a measured dead end. Prose, a
    # fourth field, or a missing cost would turn it back into a work diary.
    with pytest.raises(ProjectDeliveryError, match=message):
        normalize_delivery(_delivery(abandoned=[entry]))


def test_the_abandoned_limit_binds_the_same_in_chinese_and_english():
    # 一行的意思跟语言无关。按字符数算的时候，同一个数字在中文下是三倍的余量，
    # 于是"别写成流水账"这条规则在实际写日志的那个语言里几乎不设限。
    assert ABANDONED_FIELD_WIDTH_LIMIT == 120
    assert display_width("乙" * 60) == display_width("b" * 120) == 120
    assert display_width("ＡＢ") == 4  # fullwidth latin counts as wide too

    sixty_hanzi = {"what": "甲", "why": "乙" * 60, "cost": "半小时"}
    assert normalize_delivery(_delivery(abandoned=[sixty_hanzi]))["abandoned"][0]["why"] == "乙" * 60


def test_every_recorded_abandoned_road_still_passes_todays_limit():
    # 收紧上限不能让已经写下的记录追溯性失效——check 会红，而那些字是过去的
    # 事实，不该为了迁就新数字被改。量过：最宽的一条 118 列。
    log = load_delivery_log(ROOT / "project_delivery_log.jsonl")
    widths = [
        display_width(value)
        for record in log
        for item in record.get("abandoned") or []
        for value in item.values()
    ]

    assert widths, "the log should still carry abandoned roads to measure"
    assert max(widths) <= ABANDONED_FIELD_WIDTH_LIMIT


def test_abandoned_cli_argument_splits_into_the_three_fields():
    assert parse_abandoned_argument("放弃了什么 | 因为量过 | 半小时") == {
        "what": "放弃了什么",
        "why": "因为量过",
        "cost": "半小时",
    }

    with pytest.raises(ProjectDeliveryError, match="exactly three"):
        parse_abandoned_argument("放弃了什么|因为量过")


def test_cli_reports_a_malformed_abandoned_argument_without_a_traceback(capsys):
    # A mis-shaped `--abandoned` is a typo in a long command line. The parse
    # happens before anything is appended, so the real log stays untouched.
    code = main(
        [
            "record",
            "--id", "cli-abandoned-probe",
            "--title", "标题",
            "--product", "家里地图",
            "--kind", "architecture",
            "--summary", "摘要",
            "--touchpoint", "触点",
            "--why", "为什么",
            "--verification", "验证",
            "--path", "shenyu_gateway/project_delivery.py",
            "--abandoned", "只写了一半|没有第三段",
        ]
    )

    assert code == 2
    assert "exactly three" in capsys.readouterr().out
