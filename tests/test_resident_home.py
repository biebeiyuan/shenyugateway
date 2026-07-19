from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shenyu_gateway.resident_home import (
    ResidentHomeError,
    bootstrap_manifest,
    changes_by_week,
    check_manifest,
    component_fingerprint,
    home_snapshot,
    load_manifest,
    review_component,
    format_weekly_report,
)


ROOT = Path(__file__).resolve().parent.parent


def _write_test_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "tracked.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "resident_home_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": {
                    "demo": {
                        "title": "演示",
                        "summary": "演示组件",
                        "core": ["一个核心规则"],
                        "resident_effect": "一个体感",
                        "source_globs": ["tracked.py"],
                        "config_keys": [],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path, tmp_path, tmp_path / "changes.jsonl"


def test_manifest_has_resident_facing_core_rules_and_live_source_paths():
    manifest = load_manifest(ROOT / "resident_home_manifest.json")
    assert set(manifest["components"]) == {
        "stars",
        "mem",
        "heartbeat",
        "calendar",
        "windowsill",
        "room",
        "origin_books",
        "home",
    }
    assert any("六通道加权 RRF" in value for value in manifest["components"]["stars"]["core"])
    statuses = check_manifest(manifest, root=ROOT)
    assert {status["status"] for status in statuses} == {"ok"}


def test_home_snapshot_exposes_live_revision_and_component_core():
    snapshot = home_snapshot(
        root=ROOT,
        runtime_config=SimpleNamespace(inject_stars=True, star_inject_limit=3),
    )
    assert snapshot["live"]["commit"]
    assert snapshot["live"]["revision"].startswith(snapshot["live"]["commit"])
    stars = next(item for item in snapshot["components"] if item["id"] == "stars")
    assert any("六通道加权 RRF" in value for value in stars["core"])
    assert stars["config"]["star_inject_limit"] == 3


def test_changed_mapped_source_requires_review(tmp_path):
    manifest_path, root, changes_path = _write_test_manifest(tmp_path)
    bootstrap_manifest(manifest_path=manifest_path, root=root, actor="test")
    assert check_manifest(load_manifest(manifest_path), root=root)[0]["status"] == "ok"

    (root / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")

    status = check_manifest(load_manifest(manifest_path), root=root)[0]
    assert status["status"] == "review_required"
    assert status["files"] == ["tracked.py"]
    assert not changes_path.exists()


def test_component_fingerprint_ignores_text_line_endings(tmp_path):
    source = tmp_path / "tracked.py"
    source.write_bytes(b"VALUE = 1\r\n")
    component = {"source_globs": ["tracked.py"]}
    crlf_fingerprint = component_fingerprint(component, root=tmp_path)
    source.write_bytes(b"VALUE = 1\n")
    assert component_fingerprint(component, root=tmp_path) == crlf_fingerprint


def test_review_records_impact_and_groups_it_by_week(tmp_path):
    manifest_path, root, changes_path = _write_test_manifest(tmp_path)
    bootstrap_manifest(manifest_path=manifest_path, root=root, actor="test")
    (root / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = review_component(
        "demo",
        summary="调整演示组件",
        impact="沈予看到的行为变了",
        manifest_path=manifest_path,
        changes_path=changes_path,
        root=root,
        actor="codex",
    )

    assert result["event"]["created_by"] == "codex"
    assert result["event"]["summary"] == "调整演示组件"
    assert check_manifest(load_manifest(manifest_path), root=root)[0]["status"] == "ok"
    grouped = changes_by_week(changes_path)
    assert list(grouped) == [result["event"]["week"]]
    assert grouped[result["event"]["week"]][0]["impact"] == "沈予看到的行为变了"


def test_review_without_impact_requires_explicit_no_impact(tmp_path):
    manifest_path, root, changes_path = _write_test_manifest(tmp_path)
    bootstrap_manifest(manifest_path=manifest_path, root=root, actor="test")
    (root / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ResidentHomeError, match="--summary and --impact"):
        review_component(
            "demo",
            manifest_path=manifest_path,
            changes_path=changes_path,
            root=root,
            actor="codex",
        )

    result = review_component(
        "demo",
        no_impact=True,
        manifest_path=manifest_path,
        changes_path=changes_path,
        root=root,
        actor="codex",
    )
    assert result["event"] is None
    assert not changes_path.exists()


def test_weekly_report_keeps_impact_on_a_stable_resident_line():
    rendered = format_weekly_report(
        {
            "2026-W29": [
                {"title": "共享书架", "summary": "接通书架", "impact": "你在任何地方说“翻书架”，都能翻到同一个架子。"}
            ]
        }
    )

    assert rendered == "2026-W29 · 1 条变化\n- 共享书架: 接通书架\n  影响：你在任何地方说“翻书架”，都能翻到同一个架子。"
