from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import subprocess

from shenyu_gateway.resident_home import (
    ResidentHomeError,
    _format_line_endings,
    _print_check,
    ack_shared_components,
    bootstrap_manifest,
    changes_by_week,
    check_manifest,
    component_fingerprint,
    home_snapshot,
    load_manifest,
    review_component,
    format_weekly_report,
    home_overview,
    working_tree_line_endings,
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
        "island_bumps",
        "heartbeat",
        "calendar",
        "windowsill",
        "album",
        "orchard",
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


def test_home_overview_is_lightweight_and_keeps_confirmation_summary():
    overview = home_overview()

    assert overview["current_week"]
    assert isinstance(overview["current_week_changes"], int)
    assert overview["last_confirmed_at"]
    assert "components" not in overview


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


def _write_shared_manifest(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "shared.py").write_text("SHARED = 1\n", encoding="utf-8")
    (tmp_path / "own_a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "own_b.py").write_text("B = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "resident_home_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": {
                    "alpha": {"title": "甲", "source_globs": ["shared.py", "own_a.py"]},
                    "beta": {"title": "乙", "source_globs": ["shared.py", "own_b.py"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path, tmp_path


def test_ack_shared_acknowledges_fanout_from_shared_files_only(tmp_path):
    manifest_path, root = _write_shared_manifest(tmp_path)
    bootstrap_manifest(manifest_path=manifest_path, root=root, actor="test")

    (root / "shared.py").write_text("SHARED = 2\n", encoding="utf-8")

    statuses = {status["id"]: status for status in check_manifest(load_manifest(manifest_path), root=root)}
    assert statuses["alpha"]["status"] == "review_required"
    assert statuses["alpha"]["changed_files"] == ["shared.py"]
    assert statuses["alpha"]["shared_changed_files"] == ["shared.py"]

    result = ack_shared_components(manifest_path=manifest_path, root=root, actor="fable")

    assert {item["id"] for item in result["acked"]} == {"alpha", "beta"}
    assert result["skipped"] == []
    assert result["shared_files"] == {"shared.py": ["alpha", "beta"]}
    after = {status["id"]: status["status"] for status in check_manifest(load_manifest(manifest_path), root=root)}
    assert set(after.values()) == {"ok"}


def test_ack_shared_skips_components_with_exclusive_changes(tmp_path):
    manifest_path, root = _write_shared_manifest(tmp_path)
    bootstrap_manifest(manifest_path=manifest_path, root=root, actor="test")

    (root / "shared.py").write_text("SHARED = 2\n", encoding="utf-8")
    (root / "own_a.py").write_text("A = 2\n", encoding="utf-8")

    result = ack_shared_components(manifest_path=manifest_path, root=root, actor="fable")

    assert [item["id"] for item in result["acked"]] == ["beta"]
    assert result["skipped"][0]["id"] == "alpha"
    assert result["skipped"][0]["exclusive_files"] == ["own_a.py"]
    statuses = {status["id"]: status["status"] for status in check_manifest(load_manifest(manifest_path), root=root)}
    assert statuses == {"alpha": "review_required", "beta": "ok"}


def test_ack_shared_requires_per_file_baseline_from_older_reviews(tmp_path):
    manifest_path, root = _write_shared_manifest(tmp_path)
    bootstrap_manifest(manifest_path=manifest_path, root=root, actor="test")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for component in data["components"].values():
        component["reviewed"].pop("file_hashes")
    manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    (root / "shared.py").write_text("SHARED = 2\n", encoding="utf-8")

    statuses = {status["id"]: status for status in check_manifest(load_manifest(manifest_path), root=root)}
    assert statuses["alpha"]["changed_files"] is None

    result = ack_shared_components(manifest_path=manifest_path, root=root, actor="fable")

    assert result["acked"] == []
    assert {item["id"] for item in result["skipped"]} == {"alpha", "beta"}
    assert "baseline" in result["skipped"][0]["reason"]


def test_weekly_report_keeps_impact_on_a_stable_resident_line():
    rendered = format_weekly_report(
        {
            "2026-W29": [
                {"title": "共享书架", "summary": "接通书架", "impact": "你在任何地方说“翻书架”，都能翻到同一个架子。"}
            ]
        }
    )

    assert rendered == "2026-W29 · 1 条变化\n- 共享书架: 接通书架\n  影响：你在任何地方说“翻书架”，都能翻到同一个架子。"


def _init_repo(root: Path) -> None:
    """A repo with this repository's own eol policy, so the check sees real data."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    (root / "kept.py").write_bytes(b"KEPT = 1\n")
    (root / "drifted.py").write_bytes(b"DRIFTED = 1\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\r\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "seed"],
        cwd=root,
        check=True,
    )


def test_line_ending_check_reads_git_and_leaves_lf_and_binary_alone(tmp_path):
    _init_repo(tmp_path)

    report = working_tree_line_endings(root=tmp_path)

    assert report["checked"] is True
    assert report["files"] == []
    assert _format_line_endings(report) == []


def test_crlf_in_an_untouched_file_is_reported_without_failing_the_check(tmp_path):
    # `.gitattributes` normalizes on commit, so re-saving the same content in CRLF
    # is not a change git would carry anywhere. Inherited churn like this gets
    # named but must not leave a permanent red light this handoff cannot clear.
    _init_repo(tmp_path)
    (tmp_path / "drifted.py").write_bytes(b"DRIFTED = 1\r\n")

    report = working_tree_line_endings(root=tmp_path)

    assert [item["path"] for item in report["files"]] == ["drifted.py"]
    assert report["pending"] == []
    lines = _format_line_endings(report)
    assert len(lines) == 1
    assert "1 other tracked file(s)" in lines[0] and "drifted.py" in lines[0]
    assert _print_check([{"id": "demo", "title": "演示", "status": "ok"}], line_endings=report) == 0


def test_crlf_in_a_file_this_change_touches_fails_the_check(tmp_path, capsys):
    _init_repo(tmp_path)
    (tmp_path / "drifted.py").write_bytes(b"DRIFTED = 2\r\n")

    report = working_tree_line_endings(root=tmp_path)

    assert report["pending"] == ["drifted.py"]
    assert _print_check([{"id": "demo", "title": "演示", "status": "ok"}], line_endings=report) == 1
    printed = capsys.readouterr().out
    assert "1 file(s) you are about to commit are not LF: drifted.py" in printed


def test_a_staged_crlf_file_counts_as_pending(tmp_path):
    # Staging is when the drift is one command away from being someone else's
    # problem, so a staged file must not fall out of the actionable list.
    _init_repo(tmp_path)
    (tmp_path / "drifted.py").write_bytes(b"DRIFTED = 3\r\n")
    subprocess.run(["git", "add", "drifted.py"], cwd=tmp_path, check=True)

    assert working_tree_line_endings(root=tmp_path)["pending"] == ["drifted.py"]


def test_pending_detection_survives_a_stale_index_stat_cache(tmp_path):
    # `git status --porcelain` calls a CRLF-only rewrite modified until the index
    # stat cache refreshes, then calls it clean — so it cannot decide this. The
    # diff path runs the eol clean filter and answers the same way both times.
    _init_repo(tmp_path)
    (tmp_path / "drifted.py").write_bytes(b"DRIFTED = 1\r\n")

    first = working_tree_line_endings(root=tmp_path)["pending"]
    subprocess.run(["git", "update-index", "--refresh"], cwd=tmp_path, capture_output=True)
    assert working_tree_line_endings(root=tmp_path)["pending"] == first == []


def test_a_brand_new_crlf_file_is_visible_before_it_is_ever_added(tmp_path, capsys):
    # `ls-files --eol` reads the index, so an untracked file used to be invisible
    # to this check for exactly as long as it was the cheapest thing to fix —
    # until someone added it, at which point it became inherited churn nobody
    # owns. A file created in this session is always this handoff's to normalize.
    _init_repo(tmp_path)
    (tmp_path / "fresh.py").write_bytes(b"FRESH = 1\r\n")

    report = working_tree_line_endings(root=tmp_path)

    assert [item["path"] for item in report["files"]] == ["fresh.py"]
    assert report["files"][0]["untracked"] is True
    assert report["pending"] == ["fresh.py"]
    assert _print_check([{"id": "demo", "title": "演示", "status": "ok"}], line_endings=report) == 1
    assert "1 file(s) you are about to commit are not LF: fresh.py" in capsys.readouterr().out


def test_a_gitignored_crlf_file_is_not_this_check_s_business(tmp_path):
    # `--exclude-standard`: build output and local scratch files are not content
    # this repository carries, and flagging them would be a red light nobody can
    # clear without deleting something they wanted.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_bytes(b"scratch.py\n")
    (tmp_path / "scratch.py").write_bytes(b"SCRATCH = 1\r\n")

    assert working_tree_line_endings(root=tmp_path)["files"] == []


def test_no_git_says_so_out_loud_instead_of_looking_clean(tmp_path):
    # Printing nothing is indistinguishable from a clean check, which is how a
    # guard stops guarding without anyone noticing. Exit stays 0 — there is
    # nothing to fix here, only something the check could not see.
    report = working_tree_line_endings(root=tmp_path)

    assert report == {"checked": False, "files": [], "pending": []}
    assert _format_line_endings(report) == [
        "[line endings] skipped (no git) — this check cannot see line endings here"
    ]
    assert _print_check([{"id": "demo", "title": "演示", "status": "ok"}], line_endings=report) == 0
