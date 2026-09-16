import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

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


def test_a_file_with_history_but_no_steady_doc_is_named_too():
    # The second silence. room_tools.py earns a pointer; drifter.py has four
    # commits — well past the run floor, so it is not "too new" — and no doc
    # steady enough to clear the bar. The pointer list never says which files it
    # came from, so without this the report reads as though it covered both.
    history = HISTORY + [
        _commit("d1", "shenyu_gateway/drifter.py", "README.md"),
        _commit("d2", "shenyu_gateway/drifter.py", "DESIGN.md"),
        _commit("d3", "shenyu_gateway/drifter.py", "AGENTS.md"),
        _commit("d4", "shenyu_gateway/drifter.py"),
    ]
    report = dt.survey(
        ["shenyu_gateway/room_tools.py", "shenyu_gateway/drifter.py"],
        commits=history,
    )
    assert report["silent_sources"] == ["shenyu_gateway/drifter.py"]
    # Not the other silence: it has plenty of history, which is the whole point.
    assert report["unlearned_sources"] == []
    text = "\n".join(dt.render(report))
    assert "shenyu_gateway/drifter.py" in text
    assert "不是为它们指的" in text


def test_the_two_silences_do_not_claim_the_same_file():
    # A file below the run floor is already named as "too new". Listing it again
    # as "has history but nothing steady" would contradict that in one report.
    report = dt.survey(
        ["shenyu_gateway/lonely.py", "shenyu_gateway/room_tools.py"],
        commits=HISTORY,
    )
    assert report["unlearned_sources"] == ["shenyu_gateway/lonely.py"]
    assert report["silent_sources"] == []


def test_the_partial_silence_line_stays_out_when_nothing_was_recommended():
    # With no pointers at all, 「没有稳定跟着一起改的文档」 already says it. Saying
    # it twice would make the emptier report read as the noisier one.
    report = dt.survey(["shenyu_gateway/drifter.py"], commits=[
        _commit("d1", "shenyu_gateway/drifter.py", "README.md"),
        _commit("d2", "shenyu_gateway/drifter.py", "DESIGN.md"),
        _commit("d3", "shenyu_gateway/drifter.py", "AGENTS.md"),
    ])
    assert report["silent_sources"] == ["shenyu_gateway/drifter.py"]
    text = "\n".join(dt.render(report))
    assert "不是为它们指的" not in text
    assert "不是「不用改」" in text


def test_a_long_silent_list_is_capped_and_says_how_many_it_hid():
    # Same shape as the too-new list: a cap that does not report the total reads
    # as the whole list.
    report = {
        "commits_read": 400,
        "changed_sources": ["a.py"],
        "docs_already_touched": [],
        "pointers": [
            {"doc": "README.md", "rate": 1.0, "together": 3, "runs": 3,
             "because": "a.py", "already_touched": False}
        ],
        "silent_sources": [f"shenyu_gateway/m{i}.py" for i in range(6)],
        "unlearned_sources": [],
    }
    text = "\n".join(dt.render(report))
    assert "等 6 个" in text
    assert "shenyu_gateway/m5.py" not in text


def test_render_survives_a_report_without_the_silent_key():
    # `--json` output is read by other tools and older payloads exist; a missing
    # key must not turn advice into a traceback.
    report = {
        "commits_read": 400,
        "changed_sources": ["a.py"],
        "docs_already_touched": [],
        "pointers": [],
        "unlearned_sources": [],
    }
    assert "不是「不用改」" in "\n".join(dt.render(report))


def test_wilson_lower_bound_examples():
    # The documented examples from the docstring, verified externally
    assert abs(dt.wilson_lower_bound(3, 3) - 0.438) < 0.001
    assert abs(dt.wilson_lower_bound(4, 4) - 0.510) < 0.001
    assert abs(dt.wilson_lower_bound(11, 11) - 0.741) < 0.001


def test_wilson_sorting_ranks_high_confidence_first():
    # Wilson has to be the *deciding* key, so the case is built where every
    # other key disagrees with it:
    #
    #   AGENTS.md   3/3   rate 1.00, runs 3, lower bound ≈0.438
    #   DESIGN.md  14/16  rate 0.875, runs 16, lower bound ≈0.647
    #
    # -rate puts AGENTS.md first. Sorting on -runs would also be wrong for the
    # opposite reason (it ignores rate entirely). Only the lower bound puts
    # DESIGN.md first, so dropping the Wilson term from the sort key turns this
    # red — which the earlier 4/4-vs-11/11 version did not, because there
    # -runs happened to produce the same order.
    history = [
        _commit(f"a{i}", "shenyu_gateway/module_a.py", "AGENTS.md")
        for i in range(3)
    ] + [
        _commit(f"b{i}", "shenyu_gateway/module_b.py", "DESIGN.md")
        for i in range(14)
    ] + [
        _commit(f"c{i}", "shenyu_gateway/module_b.py")
        for i in range(2)
    ]
    together, runs = dt.learn(history)
    pointers = dt.pointers_for(
        ["shenyu_gateway/module_a.py", "shenyu_gateway/module_b.py"],
        together=together,
        runs=runs,
    )
    assert [p["doc"] for p in pointers] == ["DESIGN.md", "AGENTS.md"]
    # The stronger evidence wins even though its raw rate is lower.
    assert pointers[0]["rate"] < pointers[1]["rate"]
    # And the sort key must not survive on the returned dicts.
    assert all("_wilson_lower" not in p for p in pointers)


def test_threshold_still_judges_raw_rate_not_lower_bound():
    # Sorting changed to Wilson, but the threshold must still filter on raw rate.
    # A pointer with high raw rate but low confidence should still appear if it
    # clears min_rate — sorting is not thresholding.
    history = [
        _commit("x1", "shenyu_gateway/unstable.py", "NOTES.md"),
        _commit("x2", "shenyu_gateway/unstable.py", "NOTES.md"),
        _commit("x3", "shenyu_gateway/unstable.py"),  # 2/3 = 66.7% rate, but n=3 is weak
    ]
    together, runs = dt.learn(history)
    # With min_rate=0.5, this should produce a pointer (rate 0.667 > 0.5)
    pointers = dt.pointers_for(
        ["shenyu_gateway/unstable.py"],
        together=together,
        runs=runs,
        min_rate=0.5,
    )
    assert len(pointers) == 1
    assert pointers[0]["doc"] == "NOTES.md"
    assert pointers[0]["rate"] > 0.5

    # With min_rate=0.7, it should be filtered out (rate 0.667 < 0.7)
    pointers_strict = dt.pointers_for(
        ["shenyu_gateway/unstable.py"],
        together=together,
        runs=runs,
        min_rate=0.7,
    )
    assert len(pointers_strict) == 0


def test_backtest_scores_injected_history_instead_of_the_real_log():
    # History is injected for the same reason survey() takes it: reading this
    # repository's log makes the assertion depend on where the test runs. The
    # previous version of this test called backtest(root=ROOT) and asserted only
    # that keys existed — which passed in CI through the shallow branch and
    # locally through the real one, i.e. it pinned nothing.
    #
    # module.py: 4 runs, README.md on 3 of them (75% ≥ min_rate).
    # Leaving out m1, the model still sees 2/3 README, so m1's README is a hit.
    history = [
        _commit("m1", "shenyu_gateway/module.py", "README.md"),
        _commit("m2", "shenyu_gateway/module.py", "README.md"),
        _commit("m3", "shenyu_gateway/module.py", "README.md"),
        _commit("m4", "shenyu_gateway/module.py"),
    ]
    result = dt.backtest(commits=history)

    assert result["shallow"] is False
    assert result["commits_read"] == 4
    # Only the three commits that changed both source and a doc are eligible.
    assert result["commits_evaluated"] == 3
    assert result["precision"] == 1.0
    assert result["total_hits"] == 3
    assert result["misses"] == []
    assert result["head"] == "injected"


def test_backtest_predicts_the_direction_it_was_asked_for():
    # The predicates are not decoration: backtest must hand them to learn(), or
    # it picks eligible commits by one direction and scores them with another.
    # Dropping either argument from the learn() call turns this red, which the
    # earlier "fields exist" test could not detect.
    #
    # module_a always travels with module_b (source→source), and never with a
    # doc. Scored in the source direction it is a perfect hit; scored in the
    # default doc direction there is nothing to predict at all.
    history = [
        _commit(f"s{i}", "shenyu_gateway/module_a.py", "shenyu_gateway/module_b.py")
        for i in range(4)
    ]

    source_direction = dt.backtest(
        commits=history,
        source_predicate=dt.is_source,
        target_predicate=dt.is_source,
    )
    assert source_direction["commits_evaluated"] == 4
    assert source_direction["precision"] == 1.0
    assert source_direction["misses"] == []

    # Same history, default (doc) direction: no commit is even eligible.
    doc_direction = dt.backtest(commits=history)
    assert doc_direction["commits_evaluated"] == 0


def test_backtest_finds_the_docs_it_could_not_predict():
    # A miss must be reported with the commit that owned it, otherwise the
    # backtest log records a precision number with nothing to look at.
    history = [
        _commit("m1", "shenyu_gateway/module.py", "README.md"),
        _commit("m2", "shenyu_gateway/module.py", "README.md"),
        _commit("m3", "shenyu_gateway/module.py", "README.md"),
        # DESIGN.md rode along exactly once — never predictable, always a miss.
        _commit("m4", "shenyu_gateway/module.py", "DESIGN.md"),
    ]
    result = dt.backtest(commits=history)

    missed = {m["sha"]: m["missed_targets"] for m in result["misses"]}
    assert missed["m4"] == ["DESIGN.md"]


def test_backtest_refuses_shallow_clone():
    # CI checks out one commit. Without this branch a shallow clone returns
    # precision 0.0 with commits_evaluated 0, which is indistinguishable in the
    # jsonl from "the model predicted nothing right" — and 406b6b9 was exactly
    # that shape of bug. is_shallow is a module-level function, so it patches.
    calls = []

    def fake_learn(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError("shallow clone must return before learning")

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(dt, "is_shallow", lambda **_: True)
        monkeypatch.setattr(dt, "learn", fake_learn)
        result = dt.backtest(window=5)
    finally:
        monkeypatch.undo()

    assert result["shallow"] is True
    assert result["error"]  # says why, rather than reporting precision 0.0
    assert result["commits_evaluated"] == 0
    assert calls == []  # it really did return early


def test_module_is_runnable_with_dash_m_not_only_via_the_wrapper():
    # `python -m shenyu_gateway.doc_touchpoints` used to import the module and
    # exit 0 without calling main(): --backtest --save printed nothing and wrote
    # nothing, while the wrapper worked. A flag that is accepted and does
    # nothing is the failure mode this whole module exists to refuse.
    result = subprocess.run(
        ["python", "-m", "shenyu_gateway.doc_touchpoints", "shenyu_gateway/room_tools.py"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "-m entry produced no output at all"


def test_backtest_save_actually_writes_a_line(tmp_path, monkeypatch):
    # Step 1's whole promise is "results land on disk so months later you can
    # compare". Nothing tested that the --save path reaches the file.
    log = tmp_path / "backtest.jsonl"
    monkeypatch.setattr(dt, "BACKTEST_LOG_PATH", log)
    monkeypatch.setattr(
        dt,
        "backtest",
        lambda **_: {
            "shallow": False,
            "commits_read": 4,
            "commits_evaluated": 2,
            "precision": 0.5,
            "avg_predicted": 1.0,
            "avg_actual": 1.0,
            "misses": [],
        },
    )
    assert dt.main(["--backtest", "--save"]) == 0
    assert json.loads(log.read_text(encoding="utf-8").strip())["commits_evaluated"] == 2


def test_a_shallow_backtest_result_is_still_written_but_says_so(tmp_path):
    # The result gets persisted either way — the point is that a reader months
    # later can tell "could not measure" from "measured zero".
    result = {"shallow": True, "error": "Cannot backtest in shallow clone", "precision": 0.0}
    path = tmp_path / "backtest.jsonl"
    dt.append_backtest_result(result, path=path)
    written = json.loads(path.read_text(encoding="utf-8").strip())
    assert written["shallow"] is True
    assert written["error"]


def test_learn_uses_predicates():
    # learn() must respect source_predicate and target_predicate
    history = [
        _commit("t1", "shenyu_gateway/module_a.py", "shenyu_gateway/module_b.py", "README.md"),
        _commit("t2", "shenyu_gateway/module_a.py", "shenyu_gateway/module_b.py", "README.md"),
    ]

    # Default: source→doc
    together_doc, runs_doc = dt.learn(history)
    assert "README.md" in together_doc["shenyu_gateway/module_a.py"]

    # source→source: should learn module_a → module_b
    together_src, runs_src = dt.learn(
        history,
        source_predicate=dt.is_source,
        target_predicate=dt.is_source,
    )
    assert "shenyu_gateway/module_b.py" in together_src["shenyu_gateway/module_a.py"]
    # Should NOT learn source → doc when target_predicate=is_source
    assert "README.md" not in together_src["shenyu_gateway/module_a.py"]
