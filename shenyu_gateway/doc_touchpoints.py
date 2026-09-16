"""Which documents historically changed together with the code you just touched.

This is an observation tool, not a guardrail. It never fails and never blocks:
whether a document needs to follow a code change is a judgement call, and a
check that turned it into a verdict would teach the cheapest way to silence it
(edit one line of prose) rather than the right thing.

It learns from `git log` instead of from a maintained list. A registry of
"changed X, also read Y" would need updating by the same person who forgot to
read Y — and an entry nobody maintains reads exactly like a live one. Co-edit
history has no such empty slots: a new file simply has nothing to say yet.

Measured by leave-one-out (each commit predicted from a model trained without it).
The two measurements below answer *different questions* and are not comparable
as before/after — read the question before the number.

Question A — "on any commit that touched code, how often is a pointer right?"
This is what the tool actually experiences: every real invocation happens
without knowing whether docs were going to change.

    2026-09-15, window=60 (33 of those commits touched source):
        pointers learned from prose (a doc naming the file)  precision 17%, 4.7/commit
        pointers learned from co-edit history                precision 36%, 1.2/commit

Question B — "given that code and docs *did* change together, did we point at
the right docs?" `backtest()` answers this one, because `eligible` is
`sources and targets`. That slice drops every commit where the model predicted
something and no doc followed, i.e. exactly the zero-numerator samples, so its
precision is systematically higher than A by construction. 54% is not an
improvement over 36%; it is a different, optimistic denominator.

    2026-09-15 at HEAD 05f91d1, window=400 (262 touched source, 165 eligible):
        precision 54%, 2.35 predicted / 2.31 actual per commit

The number to quote when asking "is this tool any good in daily use" is A's 36%.
B is for tracking regressions in the ranking itself, where the denominator is
held fixed. The two windows also differ (60 vs 400), so even the sample pools
are not the same; do not diff the two numbers.

Prose lost because breadth kills precision: README.md names 68 runtime files,
so it "predicts" every change.

Precision in both is also an undercount — looking at a document and deciding it
needs nothing is a success, but only a real edit counts in the numerator.

Baseline records live in `doc_touchpoints_backtest.jsonl` (git-ignored, local
only): `--backtest --save` appends one self-contained line per run. It is not
committed because it is a measurement log, not source — comparing months apart
means comparing your own runs, so re-run it on the old commit rather than
trusting a number copied into prose.

"On the old commit" means literally checking it out. `window` counts back from
HEAD, so it names a sample pool, not a fixed range: the same `--window 400` run
in three months reads 400 different commits, and any difference then mixes model
change, history change, and pool change with no way to separate them. Checking
out the old sha slides the window back with it, which is what makes the
comparison a repetition of the same measurement rather than a new one. Running
both from today's HEAD does not compare anything. Every number in this module
therefore cites the sha it was taken at — including the two above, which is why
window=400 reads 165 eligible here and 166 in a run one commit earlier.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parent.parent
BACKTEST_LOG_PATH = ROOT / "doc_touchpoints_backtest.jsonl"

# Defaults picked by the sweep above: min_rate 0.4 raised recall 7 points but
# cost 8 points of precision and half again as many pointers; 0.6 collapsed
# recall to 18%. min_runs below 3 changed nothing measurable, so keep the
# stricter floor — one coincidence should not become a pointer.
DEFAULT_MIN_RUNS = 3
DEFAULT_MIN_RATE = 0.5
DEFAULT_WINDOW = 400

# A commit that rewrites half the tree teaches nothing about any single file:
# every document it touched would look co-edited with every file it touched.
MAX_SOURCE_FILES_PER_COMMIT = 25

SOURCE_SUFFIXES = (".py", ".ts", ".vue")
_RECORD_SEP = "\x01"


class DocTouchpointError(RuntimeError):
    """Git is unavailable or unreadable — the caller decides how loud that is."""


def _git(*args: str, root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DocTouchpointError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def wilson_lower_bound(successes: int, trials: int) -> float:
    """Wilson score confidence interval lower bound (95%).

    For a binomial proportion (successes/trials), this gives a conservative
    estimate that accounts for sample size. With few trials, even a perfect
    score gets a low bound; with many trials, the bound approaches the rate.

    Examples at 95% confidence:
        3/3   ≈ 0.438
        4/4   ≈ 0.510
        11/11 ≈ 0.741
        100/100 ≈ 0.963

    Used for sorting pointers by strength of evidence, not for thresholding.
    The threshold continues to judge raw rate, so changing the sort key cannot
    silently change which pointers are shown.
    """
    if trials == 0:
        return 0.0

    z = 1.96  # z-score for 95% confidence
    p = successes / trials
    z2 = z * z

    numerator = p + z2 / (2 * trials) - z * math.sqrt((p * (1 - p) + z2 / (4 * trials)) / trials)
    denominator = 1 + z2 / trials
    return numerator / denominator


def is_source(path: str) -> bool:
    """Runtime source, excluding tests: a test moving with a doc is coincidence."""
    if not path.endswith(SOURCE_SUFFIXES):
        return False
    parts = Path(path).parts
    return not any(part.startswith("test") for part in parts) and ".spec." not in path


def is_live_doc(path: str) -> bool:
    """Markdown that is still current. Dated snapshots are frozen by design."""
    return path.endswith(".md") and not path.startswith("docs/history/")


def read_history(
    *, window: int = DEFAULT_WINDOW, root: Path = ROOT
) -> list[tuple[str, list[str]]]:
    """(sha, changed paths) for recent non-merge commits, newest first."""
    raw = _git(
        "log",
        f"--format={_RECORD_SEP}%H",
        "--name-only",
        "--no-merges",
        f"-{int(window)}",
        root=root,
    )
    commits: list[tuple[str, list[str]]] = []
    for block in raw.split(_RECORD_SEP):
        if not block.strip():
            continue
        sha, *files = block.strip().splitlines()
        commits.append((sha.strip(), [f for f in files if f.strip()]))
    return commits


def learn(
    commits: Iterable[tuple[str, list[str]]],
    *,
    skip: str | None = None,
    source_predicate: Callable[[str], bool] = is_source,
    target_predicate: Callable[[str], bool] = is_live_doc,
) -> tuple[dict[str, Counter], Counter]:
    """Count, per source file, how often each target changed alongside it.

    `source_predicate` selects what we learn from (default: runtime source).
    `target_predicate` selects what we predict (default: live docs).
    """
    together: dict[str, Counter] = defaultdict(Counter)
    runs: Counter = Counter()
    for sha, files in commits:
        if skip is not None and sha == skip:
            continue
        sources = [f for f in files if source_predicate(f)]
        if not sources or len(sources) > MAX_SOURCE_FILES_PER_COMMIT:
            continue
        targets = [f for f in files if target_predicate(f)]
        for source in set(sources):
            runs[source] += 1
            for target in set(targets):
                together[source][target] += 1
    return together, runs


def pointers_for(
    paths: Iterable[str],
    *,
    together: dict[str, Counter],
    runs: Counter,
    min_runs: int = DEFAULT_MIN_RUNS,
    min_rate: float = DEFAULT_MIN_RATE,
) -> list[dict[str, Any]]:
    """Docs worth a look for these paths, strongest first.

    Each pointer carries the count it was learned from, because "6 of 6 times"
    and "3 of 6 times" deserve different amounts of trust and the reader can
    only weigh that if the tool shows its evidence.

    Pointers are sorted by Wilson score lower bound (95% confidence), which
    accounts for sample size: 4/4 (lower bound ≈0.51) ranks below 11/11
    (≈0.74), even though both are 100%. The threshold continues to judge raw
    rate, so only sorting changed — a pointer that clears min_rate will always
    be shown, regardless of its lower bound.

    Tie-breaking: when two pointers have the same lower bound (rare but possible),
    sort by (-rate, -runs, doc) for determinism.
    """
    best: dict[str, dict[str, Any]] = {}
    for path in sorted(set(paths)):
        total = runs.get(path, 0)
        if total < min_runs:
            continue
        for doc, n in together.get(path, {}).items():
            rate = n / total
            if rate < min_rate:
                continue
            previous = best.get(doc)
            if previous is None or rate > previous["rate"]:
                best[doc] = {
                    "doc": doc,
                    "rate": rate,
                    "together": n,
                    "runs": total,
                    "because": path,
                }

    # Wilson lower bound is computed inside the sort key, never stored: a key
    # that lives on the returned dict even briefly invites someone to read it
    # after the sort, and then the behaviour depends on when it was deleted.
    return sorted(
        best.values(),
        key=lambda p: (
            -wilson_lower_bound(p["together"], p["runs"]),
            -p["rate"],
            -p["runs"],
            p["doc"],
        ),
    )


def changed_paths(*, staged_only: bool = False, root: Path = ROOT) -> list[str]:
    """What the working tree has changed, including files not yet added.

    Untracked files count: a brand-new module is exactly the case where nobody
    has read the surrounding docs yet.
    """
    if staged_only:
        return sorted(set(_git("diff", "--cached", "--name-only", root=root).split()))
    names = set(_git("diff", "--name-only", "HEAD", root=root).split())
    names.update(
        _git("ls-files", "--others", "--exclude-standard", root=root).split()
    )
    return sorted(names)


def is_shallow(*, root: Path = ROOT) -> bool:
    """A shallow clone has no co-edit history to learn from — CI checks out one
    commit by default, so silence there means "cannot know", not "nothing to do".
    """
    return _git("rev-parse", "--is-shallow-repository", root=root).strip() == "true"


def survey(
    paths: Iterable[str] | None = None,
    *,
    staged_only: bool = False,
    window: int = DEFAULT_WINDOW,
    min_runs: int = DEFAULT_MIN_RUNS,
    min_rate: float = DEFAULT_MIN_RATE,
    root: Path = ROOT,
    commits: Iterable[tuple[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """The whole report: what changed, what to look at, what it cannot know.

    `commits` is injectable so tests can state their own history. A test that
    leans on this repository's real log passes or fails by where it runs: the
    first version of this file had one, and it went red in CI only, where
    `actions/checkout` clones a single commit.
    """
    if paths is None:
        paths = changed_paths(staged_only=staged_only, root=root)
    paths = sorted(set(paths))
    sources = [p for p in paths if is_source(p)]
    docs_touched = [p for p in paths if is_live_doc(p)]

    shallow = False
    if commits is None:
        commits = read_history(window=window, root=root)
        shallow = is_shallow(root=root)
    commits = list(commits)
    together, runs = learn(commits)
    pointers = pointers_for(
        sources,
        together=together,
        runs=runs,
        min_runs=min_runs,
        min_rate=min_rate,
    )
    # Files too new to have taught anything. Reported rather than hidden: the
    # tool going quiet on a brand-new module is its main blind spot, and a
    # blind spot the reader cannot see is worse than one it can.
    unlearned = [p for p in sources if runs.get(p, 0) < min_runs]
    # The other silence, which used to have no sentence of its own: enough
    # history to learn from, but no document steady enough to clear the bar.
    # A pointer list does not say which files it came from, so a report
    # covering two of four changed files read exactly like one covering all
    # four. Asked one file at a time on purpose — reimplementing the threshold
    # test here is how the two copies would drift apart.
    too_new = set(unlearned)
    silent = [
        p
        for p in sources
        if p not in too_new
        and not pointers_for(
            [p],
            together=together,
            runs=runs,
            min_runs=min_runs,
            min_rate=min_rate,
        )
    ]
    return {
        "commits_read": len(commits),
        "shallow": shallow,
        "changed_sources": sources,
        "docs_already_touched": docs_touched,
        "pointers": [
            {**pointer, "already_touched": pointer["doc"] in set(docs_touched)}
            for pointer in pointers
        ],
        "silent_sources": silent,
        "unlearned_sources": unlearned,
    }


def _name_list(paths: list[str], limit: int = 4) -> str:
    """Full paths, capped, with the total when it was capped.

    Full paths rather than basenames: `scripts/` and `shenyu_gateway/` hold
    same-named pairs by convention, and two identical names in one list read as
    one file listed twice.
    """
    shown = "、".join(paths[:limit])
    return f"{shown} 等 {len(paths)} 个" if len(paths) > limit else shown


def render(report: dict[str, Any]) -> list[str]:
    """Plain lines for a terminal. Wording stays advisory on purpose."""
    lines: list[str] = []
    sources = report["changed_sources"]
    if not sources:
        lines.append("没有改动的源码文件，无从推荐。")
        return lines

    lines.append(f"改了 {len(sources)} 个源码文件，按 {report['commits_read']} 个提交的同改历史看：")
    if report.get("shallow"):
        # Say it, don't just fall quiet: a shallow clone (CI's default checkout)
        # looks exactly like a repository where nothing ever changed together.
        lines.append("  这是浅克隆，只有一个提交，学不到任何同改历史——不是没线索，是看不到。")
    if not report["pointers"] and not report.get("shallow"):
        lines.append("  历史上没有稳定跟着一起改的文档。不是「不用改」，只是这次没有线索。")
    for pointer in report["pointers"]:
        mark = "✓" if pointer["already_touched"] else "·"
        lines.append(
            f"  {mark} {pointer['doc']}"
            f"  {pointer['rate']:.0%}（{pointer['together']}/{pointer['runs']} 次跟着"
            f" {Path(pointer['because']).name} 一起改）"
        )
    if any(not pointer["already_touched"] for pointer in report["pointers"]):
        lines.append("  ✓ 是这次已经改过的；· 是还没碰过的，值得看一眼再决定。")
    if report.get("silent_sources") and report["pointers"]:
        # Only when something was recommended: a report with pointers reads as
        # if it covered every changed file, because the list above never says
        # which files it came from. With no pointers at all the 没有稳定 line
        # above already says it, and saying it twice makes the shorter case
        # look like the noisier one.
        names = _name_list(report["silent_sources"])
        lines.append(f"  这些文件有历史但没有稳定跟着改的文档，上面那几条不是为它们指的：{names}")
    if report["unlearned_sources"]:
        names = _name_list(report["unlearned_sources"])
        lines.append(f"  这些文件历史太短，学不到东西，得自己判断：{names}")
    lines.append("  这只是提醒，文档要不要跟着改是判断题，它不判红也不拦提交。")
    return lines


def _backtest_result(
    *,
    head_sha: str,
    window: int,
    min_runs: int,
    min_rate: float,
    commits_read: int,
    shallow: bool = False,
    error: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The one shape every `backtest()` return has, zeroed unless `metrics` says otherwise.

    All three exits go through here — measured, nothing eligible, shallow clone —
    so the key set cannot depend on which branch produced it. They used to
    hand-write the dict separately and had already drifted: the empty-eligible
    branch was missing total_hits / total_predicted / total_actual, so a `--json`
    consumer saw those keys appear and disappear depending on the history it was
    pointed at.

    `metrics` may only overwrite keys that already exist here, which is asserted
    rather than documented: an update that introduces a key would recreate the
    same drift through a smaller door, and the parity test in
    tests/test_doc_touchpoints.py could then only report it after the fact. This
    way the measuring path cannot grow a field the empty paths lack.

    `error` is the one key that is legitimately branch-specific — a shallow clone
    cannot know, an empty eligible set knows there was nothing — so it is only
    added when set.
    """
    result: dict[str, Any] = {
        "head": head_sha,
        "timestamp": datetime.now().isoformat(),
        "window": window,
        "min_runs": min_runs,
        "min_rate": min_rate,
        "shallow": shallow,
        "commits_read": commits_read,
        "commits_evaluated": 0,
        "precision": 0.0,
        "avg_predicted": 0.0,
        "avg_actual": 0.0,
        "total_hits": 0,
        "total_predicted": 0,
        "total_actual": 0,
        "misses": [],
    }
    if metrics:
        unknown = sorted(set(metrics) - set(result))
        if unknown:
            raise DocTouchpointError(
                f"backtest metrics introduced keys the empty result lacks: {unknown} "
                "— add them to _backtest_result instead, or every exit stops agreeing"
            )
        result.update(metrics)
    if error is not None:
        result["error"] = error
    return result


def backtest(
    *,
    window: int = DEFAULT_WINDOW,
    min_runs: int = DEFAULT_MIN_RUNS,
    min_rate: float = DEFAULT_MIN_RATE,
    root: Path = ROOT,
    commits: Iterable[tuple[str, list[str]]] | None = None,
    target_predicate: Callable[[str], bool] = is_live_doc,
    source_predicate: Callable[[str], bool] = is_source,
) -> dict[str, Any]:
    """Leave-one-out validation: measure precision on recent commits.

    For each commit in the window that changed both sources and targets, train
    on all other commits and measure whether the model predicts the targets that
    actually changed. Returns aggregated metrics plus the list of misses.

    `target_predicate` selects what we're trying to predict (default: live docs).
    `source_predicate` selects what we predict from (default: runtime source).

    `commits` is injectable for the same reason `survey()` accepts it: a test
    that reads this repository's real log passes or fails by where it runs. When
    injected, the shallow check is skipped — the caller stated the history, so
    there is nothing to be shallow about.

    Precision here answers "given that docs did change, did we point at the
    right ones?" — `eligible` requires both sources and targets, which drops
    every zero-numerator commit and makes this number optimistic by
    construction. See the module docstring: it is not comparable to the
    all-commits measurement.

    This cannot detect feedback loops: if agents start following the tool's
    suggestions, history gradually becomes the tool's own shape, and leave-one-out
    precision rises for the wrong reason. Distinguishing "model improved" from
    "agents conformed" would require recording what was pointed at during each
    record() call, then measuring how often those pointers were followed.

    Cost: it re-learns the whole window once per eligible commit, so time grows
    with window × eligible. Measured 2026-09-15 at HEAD 05f91d1, so a sweep is
    not mistaken for a hang:

        window= 60 →  18 eligible → 0.06s
        window=200 →  59 eligible → 0.32s
        window=400 → 165 eligible → 1.98s
        window=800 → 241 eligible → 4.52s  (history exhausts at 599 commits)

    A parameter sweep multiplies that by the number of points. Seconds, not
    minutes, at present size — worth re-measuring before assuming so. The window
    slides with HEAD, so eligible counts drift by a commit or two between runs;
    that is why every number in this module cites the sha it was taken at.
    """
    injected = commits is not None
    if injected:
        commits = list(commits)
        head_sha = "injected"
        shallow = False
    else:
        commits = read_history(window=window, root=root)
        head_sha = _git("rev-parse", "HEAD", root=root).strip()
        shallow = is_shallow(root=root)

    # Refuse to run in shallow clones — precision would be meaningless
    if shallow:
        return _backtest_result(
            head_sha=head_sha,
            window=window,
            min_runs=min_runs,
            min_rate=min_rate,
            commits_read=len(commits),
            shallow=True,
            error="Cannot backtest in shallow clone — no history to learn from",
        )

    # Only evaluate commits that changed both sources and targets
    eligible = []
    for sha, files in commits:
        sources = [f for f in files if source_predicate(f)]
        targets = [f for f in files if target_predicate(f)]
        if sources and targets:
            eligible.append((sha, sources, targets))

    if not eligible:
        return _backtest_result(
            head_sha=head_sha,
            window=window,
            min_runs=min_runs,
            min_rate=min_rate,
            commits_read=len(commits),
        )

    total_hits = 0
    total_predicted = 0
    total_actual = 0
    misses: list[dict[str, Any]] = []

    for sha, sources, actual_targets in eligible:
        # Train on everything except this commit
        together, runs = learn(
            commits,
            skip=sha,
            source_predicate=source_predicate,
            target_predicate=target_predicate,
        )
        predicted = pointers_for(
            sources,
            together=together,
            runs=runs,
            min_runs=min_runs,
            min_rate=min_rate,
        )
        predicted_set = {p["doc"] for p in predicted}
        actual_set = set(actual_targets)

        hits = len(predicted_set & actual_set)
        total_hits += hits
        total_predicted += len(predicted_set)
        total_actual += len(actual_set)

        missed = sorted(actual_set - predicted_set)
        if missed:
            misses.append({
                "sha": sha,
                "sources": sources,
                "missed_targets": missed,
                "predicted": sorted(predicted_set),
            })

    precision = total_hits / total_predicted if total_predicted > 0 else 0.0

    return _backtest_result(
        head_sha=head_sha,
        window=window,
        min_runs=min_runs,
        min_rate=min_rate,
        commits_read=len(commits),
        metrics={
            "commits_evaluated": len(eligible),
            "precision": round(precision, 4),
            "avg_predicted": round(total_predicted / len(eligible), 2),
            "avg_actual": round(total_actual / len(eligible), 2),
            "total_hits": total_hits,
            "total_predicted": total_predicted,
            "total_actual": total_actual,
            "misses": misses,
        },
    )


def append_backtest_result(
    result: dict[str, Any],
    path: Path | None = None,
) -> None:
    """Persist one backtest run to the JSONL log.

    Each line is self-contained: HEAD sha, timestamp, full config, metrics, and
    the list of misses. Without the config, comparing runs months apart is
    meaningless — you can't tell if a difference comes from history or parameters.

    The default is resolved at call time, not bound as a default argument: a
    module-level default freezes BACKTEST_LOG_PATH at import, so a test that
    redirects it writes into the real log instead. That happened.
    """
    if path is None:
        path = BACKTEST_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show which documents historically changed with the code you touched.",
    )
    # Allow positional arguments at top level for backward compatibility
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to ask about. Default: everything changed in the working tree.",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Ask about staged changes only.",
    )
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS)
    parser.add_argument("--min-rate", type=float, default=DEFAULT_MIN_RATE)
    parser.add_argument("--json", dest="as_json", action="store_true")

    # Backtest mode
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run leave-one-out validation instead of surveying changes.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="(With --backtest) Append results to doc_touchpoints_backtest.jsonl",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.backtest:
        try:
            result = backtest(
                window=args.window,
                min_runs=args.min_runs,
                min_rate=args.min_rate,
            )
        except DocTouchpointError as exc:
            print(f"backtest: 读不到历史：{exc}")
            return 0

        if args.save:
            append_backtest_result(result)
            if result.get("error"):
                print(f"[saved with error] {result['error']}")
            else:
                print(f"[saved] {result['commits_evaluated']} commits, precision {result['precision']:.1%}")

        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            # Summary only, no misses list in non-JSON mode
            print(f"shallow: {result.get('shallow', False)}")
            print(f"commits_read: {result.get('commits_read', 0)}")
            print(f"commits_evaluated: {result['commits_evaluated']}")
            if result.get("error"):
                print(f"error: {result['error']}")
            else:
                print(f"precision: {result['precision']:.1%}")
                print(f"avg_predicted: {result['avg_predicted']}")
                print(f"avg_actual: {result['avg_actual']}")
                if result['commits_evaluated'] > 0:
                    print(f"misses: {len(result['misses'])} commits with unpredicted docs")
        return 0

    # Default: survey
    try:
        report = survey(
            args.paths or None,
            staged_only=args.staged,
            window=args.window,
            min_runs=args.min_runs,
            min_rate=args.min_rate,
        )
    except DocTouchpointError as exc:
        # No git, no history, no advice — and still exit 0. This tool is never
        # the reason a piece of work stops.
        print(f"读不到同改历史：{exc}")
        return 0
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for line in render(report):
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    # Without this, `python -m shenyu_gateway.doc_touchpoints --backtest --save`
    # imports the module, never calls main(), prints nothing and exits 0 — the
    # exact silence this tool is built to refuse. scripts/doc_touchpoints.py
    # worked, so the flag looked accepted while doing nothing.
    raise SystemExit(main())
