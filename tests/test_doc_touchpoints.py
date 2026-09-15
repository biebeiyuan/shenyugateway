import subprocess
from collections import Counter
from pathlib import Path

from shenyu_gateway import doc_touchpoints as dt


def _commit(sha: str, *files: str) -> tuple[str, list[str]]:
    return sha, list(files)


HISTORY = [
    _commit("a1", "shenyu_gateway/room_tools.py", "docs/architecture/MEMORY_ROOM.md"),
    _commit("a2", "shenyu_gateway/room_tools.py", "docs/architecture/MEMORY_ROOM.md"),
    _commit("a3", "shenyu_gateway/room_tools.py", "docs/architecture/MEMORY_ROOM.md"),
    _commit("a4", "shenyu_gateway/room_tools.py", "README.md"),
    _commit("b1", "shenyu_gateway/lonely.py"),
]


def test_a_doc_that_usually_follows_becomes_a_pointer_with_its_evidence():
    together, runs = dt.learn(HISTORY)
    pointers = dt.pointers_for(
        ["shenyu_gateway/room_tools.py"], together=together, runs=runs
    )
    assert [p["doc"] for p in pointers] == ["docs/architecture/MEMORY_ROOM.md"]
    # The count travels with the pointer: 3-of-4 and 4-of-4 deserve different
    # trust, and the reader can only weigh that if the evidence is shown.
    assert pointers[0]["together"] == 3
    assert pointers[0]["runs"] == 4
    assert pointers[0]["rate"] == 0.75
    assert pointers[0]["because"] == "shenyu_gateway/room_tools.py"


def test_a_doc_that_followed_once_is_not_a_pointer():
    # README.md rode along on exactly one of four commits. Promoting that would
    # be how the tool turns into noise, which is what the measurement rejected.
    together, runs = dt.learn(HISTORY)
    docs = {
        p["doc"]
        for p in dt.pointers_for(
            ["shenyu_gateway/room_tools.py"], together=together, runs=runs
        )
    }
    assert "README.md" not in docs


def test_a_file_below_the_run_floor_stays_silent_rather_than_guessing():
    # One co-edit is a coincidence. lonely.py has a single commit and no doc, so
    # it must produce nothing at all — not a weak pointer with a low score.
    together, runs = dt.learn(HISTORY)
    assert runs["shenyu_gateway/lonely.py"] == 1
    assert dt.pointers_for(
        ["shenyu_gateway/lonely.py"], together=together, runs=runs
    ) == []


def test_unreachable_git_raises_so_callers_can_choose_the_volume():
    try:
        dt.read_history(root=Path("/nonexistent"))
    except (dt.DocTouchpointError, FileNotFoundError):
        pass  # Either way it is loud here; main() turns it into one quiet line.
    else:
        raise AssertionError("reading history from a missing root should fail")


def test_sweeping_commits_do_not_teach_anything():
    # A commit rewriting the tree would pair every doc with every file, so the
    # widest commits are excluded. Without this, one big refactor makes every
    # pointer look strong.
    wide = [
        _commit(
            "big",
            *[f"shenyu_gateway/mod{i}.py" for i in range(dt.MAX_SOURCE_FILES_PER_COMMIT + 1)],
            "DESIGN.md",
        )
    ]
    together, runs = dt.learn(wide)
    assert not together
    assert not runs


def test_tests_and_dated_snapshots_are_not_part_of_the_signal():
    assert dt.is_source("shenyu_gateway/room_tools.py")
    assert dt.is_source("pwa/src/api/useUpstream.ts")
    assert not dt.is_source("tests/test_room_newspaper.py")
    assert not dt.is_source("admin/src/api/config.spec.ts")
    assert not dt.is_source("README.md")
    assert dt.is_live_doc("docs/architecture/MEMORY_ROOM.md")
    # Dated snapshots record what was true then; they never need to follow code.
    assert not dt.is_live_doc("docs/history/2026-08-review.md")


def test_leave_one_out_is_possible_so_the_model_can_be_measured_honestly():
    # The skip argument exists so a commit can be predicted from a model that
    # never saw it. Without it, any accuracy claim about this tool would be
    # trained on the answer.
    together, runs = dt.learn(HISTORY, skip="a3")
    assert runs["shenyu_gateway/room_tools.py"] == 3
    assert together["shenyu_gateway/room_tools.py"]["docs/architecture/MEMORY_ROOM.md"] == 2


def test_a_pointer_already_edited_is_marked_so_it_is_not_re_read():
    # History is injected, not read from this repository. The first version of
    # this test used the real log and passed locally while failing in CI, where
    # actions/checkout clones a single commit and nothing can be learned.
    report = dt.survey(
        ["shenyu_gateway/room_tools.py", "docs/architecture/MEMORY_ROOM.md"],
        commits=HISTORY,
    )
    docs = {p["doc"]: p["already_touched"] for p in report["pointers"]}
    assert docs.get("docs/architecture/MEMORY_ROOM.md") is True


def test_a_shallow_clone_says_it_cannot_know_instead_of_going_quiet():
    # CI checks out one commit by default. Silence there is indistinguishable
    # from "these files never travel with a document", so it has to be named.
    report = dict(dt.survey(["shenyu_gateway/room_tools.py"], commits=[]))
    report["shallow"] = True
    text = "\n".join(dt.render(report))
    assert "浅克隆" in text
    assert "看不到" in text


def test_the_report_names_the_files_it_cannot_advise_on():
    # A file below the run floor must be named, not silently skipped — an
    # invisible blind spot is the worse one. History is injected so this keeps
    # testing the mechanism as the real file accumulates commits.
    report = dt.survey(
        ["shenyu_gateway/doc_touchpoints.py"],
        commits=[_commit("z1", "shenyu_gateway/doc_touchpoints.py", "README.md")],
    )
    assert "shenyu_gateway/doc_touchpoints.py" in report["unlearned_sources"]
    text = "\n".join(dt.render(report))
    assert "学不到东西" in text
    # Full paths, because scripts/ and shenyu_gateway/ hold same-named pairs by
    # convention and two identical basenames read as one file listed twice.
    assert "shenyu_gateway/doc_touchpoints.py" in text


def test_the_tool_never_blocks_work():
    # Advice cannot be a gate: whether a doc must follow is a judgement call,
    # and a red light here would teach editing one line of prose to silence it.
    assert dt.main(["shenyu_gateway/room_tools.py"]) == 0
    assert dt.main(["--json", "shenyu_gateway/room_tools.py"]) == 0
    assert dt.main(["docs/architecture/MEMORY_ROOM.md"]) == 0


def test_unreadable_history_is_reported_and_still_exits_zero(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise dt.DocTouchpointError("no git here")

    monkeypatch.setattr(dt, "survey", boom)
    assert dt.main([]) == 0
    assert "读不到同改历史" in capsys.readouterr().out


def test_the_script_wrapper_runs_from_the_repo_root():
    result = subprocess.run(
        ["python", "scripts/doc_touchpoints.py", "shenyu_gateway/room_tools.py"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "同改历史" in result.stdout


def test_render_says_no_clue_rather_than_no_need():
    # The difference matters: silence must not read as permission.
    report = {
        "commits_read": 400,
        "changed_sources": ["shenyu_gateway/whatever.py"],
        "docs_already_touched": [],
        "pointers": [],
        "unlearned_sources": [],
    }
    text = "\n".join(dt.render(report))
    assert "不是「不用改」" in text
    report["changed_sources"] = []
    assert "无从推荐" in "\n".join(dt.render(report))


def test_pointers_keep_the_strongest_evidence_when_two_files_agree():
    history = HISTORY + [
        _commit("c1", "shenyu_gateway/room_text.py", "docs/architecture/MEMORY_ROOM.md"),
        _commit("c2", "shenyu_gateway/room_text.py", "docs/architecture/MEMORY_ROOM.md"),
        _commit("c3", "shenyu_gateway/room_text.py", "docs/architecture/MEMORY_ROOM.md"),
    ]
    together, runs = dt.learn(history)
    pointers = dt.pointers_for(
        ["shenyu_gateway/room_tools.py", "shenyu_gateway/room_text.py"],
        together=together,
        runs=runs,
    )
    assert len(pointers) == 1
    # room_text.py is 3/3, room_tools.py is 3/4 — the reader should see the
    # stronger reason, not whichever path sorted first.
    assert pointers[0]["because"] == "shenyu_gateway/room_text.py"
    assert pointers[0]["rate"] == 1.0


def test_counters_are_plain_so_a_missing_file_is_zero_not_an_error():
    assert dt.pointers_for(["nope.py"], together={}, runs=Counter()) == []
