from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .runtime import LOCAL_DAY_TZ


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "resident_home_manifest.json"
CHANGES_PATH = ROOT / "resident_home_changes.jsonl"


class ResidentHomeError(ValueError):
    """Raised when the resident-home mapping cannot be trusted."""


def _now() -> datetime:
    return datetime.now(LOCAL_DAY_TZ).replace(microsecond=0)


def week_key(value: datetime | None = None) -> str:
    current = value or _now()
    iso = current.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _git(*args: str, root: Path = ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def current_commit(root: Path = ROOT) -> str:
    return (
        _git("rev-parse", "HEAD", root=root)
        or os.getenv("SHENYU_BUILD_COMMIT", "").strip()
        or os.getenv("GIT_COMMIT_SHA", "").strip()
        or os.getenv("SOURCE_COMMIT", "").strip()
    )


def worktree_dirty(root: Path = ROOT) -> bool:
    return bool(_git("status", "--porcelain", root=root))


def _paths_changed_from_head(root: Path = ROOT) -> set[str]:
    """Tracked paths whose content differs from HEAD, staged or not.

    Deliberately not `git status --porcelain`: a rewrite that only flipped line
    endings shows up there as modified until the index stat cache refreshes, then
    goes clean. `git diff` runs the `eol=lf` clean filter, so it answers the
    question that matters — would committing this file change anything — with the
    same answer every time. `-z` keeps paths raw instead of shell-quoted.
    """
    listing = _git("diff", "--name-only", "-z", "HEAD", root=root)
    return {path for path in listing.split("\0") if path}


def current_revision(root: Path = ROOT) -> str:
    commit = current_commit(root)
    if not commit:
        return ""
    return f"{commit}-dirty" if worktree_dirty(root) else commit


def current_actor(root: Path = ROOT) -> str:
    configured = os.getenv("RESIDENT_HOME_ACTOR", "").strip()
    if configured:
        return configured
    return _git("config", "user.name", root=root) or "resident-agent"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResidentHomeError(f"cannot read manifest {path}: {exc}") from exc
    components = data.get("components")
    if data.get("schema_version") != 1 or not isinstance(components, dict) or not components:
        raise ResidentHomeError("resident_home_manifest.json must contain schema_version=1 and components")
    for component_id, component in components.items():
        if not isinstance(component, dict) or not str(component.get("title") or "").strip():
            raise ResidentHomeError(f"component {component_id!r} has no title")
        globs = component.get("source_globs")
        if not isinstance(globs, list) or not globs:
            raise ResidentHomeError(f"component {component_id!r} has no source_globs")
    return data


def _source_files(component: dict[str, Any], root: Path) -> list[tuple[str, Path]]:
    matches: dict[str, Path] = {}
    for pattern in component.get("source_globs") or []:
        for path in root.glob(str(pattern)):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                matches[relative] = path
    return sorted(matches.items())


def _source_state(component: dict[str, Any], root: Path = ROOT) -> tuple[str, dict[str, str]]:
    """Return (component fingerprint, per-file hashes) in one pass.

    The combined digest must stay byte-identical to the historical
    ``component_fingerprint`` algorithm — changing it would flag every
    component as review_required on upgrade.
    """
    files = _source_files(component, root)
    if not files:
        raise ResidentHomeError("source_globs did not match any files")
    digest = hashlib.sha256()
    file_hashes: dict[str, str] = {}
    for relative, path in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        # Mapped sources are text files, and this repo is edited from both
        # WSL and Windows clients. Normalize line endings so a checkout does
        # not create a false resident-review alarm.
        normalized = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(normalized)
        digest.update(b"\0")
        file_hashes[relative] = hashlib.sha256(normalized).hexdigest()
    return digest.hexdigest(), file_hashes


def component_fingerprint(component: dict[str, Any], root: Path = ROOT) -> str:
    return _source_state(component, root)[0]


# git's own eol column values that need no attention: pure LF, an empty file,
# and anything git classifies as binary.
_LINE_ENDING_OK = frozenset({"lf", "none", "-text"})


def working_tree_line_endings(root: Path = ROOT) -> dict[str, Any]:
    """Text files in the worktree, tracked or not, whose copy on disk is not pure LF.

    ``_source_state`` normalizes line endings before hashing, so this module reads
    every mapped source and deliberately looks away from how its lines end. This
    command runs before every resident review, which makes it the cheapest place to
    close that blind spot instead of trusting anyone to remember.

    ``.gitattributes`` sets ``eol=lf``, so committed content is LF whatever the
    client does and non-LF bytes never reach the repository. What this finds is
    local worktree drift — a Windows-side write leaving a stray CR inside a string
    literal, or half a file rewritten in the other style. git decides what counts
    as text, so binaries and empty files fall out for free.

    ``--others --exclude-standard`` is what makes a brand new file visible: plain
    ``ls-files --eol`` only reports the index, so a file written in CRLF and not yet
    ``git add``-ed was invisible to this check for exactly as long as it was the
    easiest thing to fix. A new file is also always ``pending`` — the concession for
    inherited churn exists because an old tracked file's endings are not this
    handoff's fault, and a file created in this session is.
    """
    listing = _git("ls-files", "--eol", "--cached", "--others", "--exclude-standard", root=root)
    if not listing:
        return {"checked": False, "files": [], "pending": []}
    changed = _paths_changed_from_head(root)
    offenders: list[dict[str, Any]] = []
    for line in listing.splitlines():
        attributes, separator, relative = line.partition("\t")
        if not separator:
            continue
        fields = attributes.split()
        if len(fields) < 2:
            continue
        worktree_eol = fields[1].partition("/")[2]
        if worktree_eol in _LINE_ENDING_OK:
            continue
        # An untracked file has nothing in the index, so git leaves that column
        # bare — the one signal here for "this file is new".
        untracked = not fields[0].partition("/")[2]
        path = relative.strip()
        offenders.append(
            {
                "path": path,
                "eol": worktree_eol,
                "untracked": untracked,
                "pending": untracked or path in changed,
            }
        )
    offenders.sort(key=lambda item: item["path"])
    return {
        "checked": True,
        "files": offenders,
        # Drift in a file this handoff is about to commit is the actionable case
        # and fails `check`. The rest is inherited churn from earlier sessions:
        # reported, but not a standing red light nobody can clear.
        "pending": [item["path"] for item in offenders if item["pending"]],
    }


def source_owner_map(manifest: dict[str, Any], root: Path = ROOT) -> dict[str, list[str]]:
    """Map each mapped source file to the components that claim it."""
    owners: dict[str, list[str]] = {}
    for component_id, component in manifest["components"].items():
        for relative, _ in _source_files(component, root):
            owners.setdefault(relative, []).append(component_id)
    return owners


def component_status(
    component_id: str,
    component: dict[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    files = _source_files(component, root)
    if not files:
        return {
            "id": component_id,
            "title": component.get("title") or component_id,
            "status": "error",
            "error": "source_globs did not match any files",
            "files": [],
        }
    fingerprint, file_hashes = _source_state(component, root)
    reviewed = component.get("reviewed") or {}
    reviewed_fingerprint = str(reviewed.get("fingerprint") or "")
    recorded_hashes = reviewed.get("file_hashes")
    changed_files: list[str] | None = None
    if isinstance(recorded_hashes, dict) and recorded_hashes:
        changed_files = sorted(
            {
                relative
                for relative, value in file_hashes.items()
                if recorded_hashes.get(relative) != value
            }
            | (set(recorded_hashes) - set(file_hashes))
        )
    return {
        "id": component_id,
        "title": component.get("title") or component_id,
        "status": "ok" if reviewed_fingerprint == fingerprint else "review_required",
        "fingerprint": fingerprint,
        "reviewed_fingerprint": reviewed_fingerprint,
        "files": [relative for relative, _ in files],
        "file_hashes": file_hashes,
        # None means the last review predates per-file baselines and the
        # change cannot be attributed to specific files.
        "changed_files": changed_files,
        "reviewed": reviewed,
    }


def check_manifest(
    manifest: dict[str, Any] | None = None,
    *,
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    data = manifest or load_manifest(root / "resident_home_manifest.json")
    owners = source_owner_map(data, root)
    statuses = []
    for component_id, component in data["components"].items():
        status = component_status(component_id, component, root=root)
        changed = status.get("changed_files")
        if changed is not None:
            status["shared_changed_files"] = [
                relative for relative in changed if len(owners.get(relative) or []) >= 2
            ]
        statuses.append(status)
    return statuses


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_change(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def bootstrap_manifest(
    *,
    manifest_path: Path = MANIFEST_PATH,
    root: Path = ROOT,
    actor: str | None = None,
) -> dict[str, Any]:
    data = load_manifest(manifest_path)
    stamp = _now().isoformat()
    commit = current_commit(root)
    dirty = worktree_dirty(root)
    reviewer = actor or current_actor(root)
    for component_id, component in data["components"].items():
        status = component_status(component_id, component, root=root)
        if status["status"] == "error":
            raise ResidentHomeError(f"{component_id}: {status['error']}")
        component["reviewed"] = {
            "fingerprint": status["fingerprint"],
            "file_hashes": status["file_hashes"],
            "commit": commit,
            "revision": f"{commit}-dirty" if dirty and commit else commit,
            "worktree_dirty": dirty,
            "reviewed_at": stamp,
            "reviewed_by": reviewer,
        }
    _write_json(manifest_path, data)
    return data


def review_component(
    component_id: str,
    *,
    summary: str = "",
    impact: str = "",
    no_impact: bool = False,
    manifest_path: Path = MANIFEST_PATH,
    changes_path: Path = CHANGES_PATH,
    root: Path = ROOT,
    actor: str | None = None,
) -> dict[str, Any]:
    data = load_manifest(manifest_path)
    component = data["components"].get(component_id)
    if not component:
        raise ResidentHomeError(f"unknown resident-home component: {component_id}")
    if not no_impact and (not summary.strip() or not impact.strip()):
        raise ResidentHomeError("resident-impact review requires --summary and --impact, or use --no-impact")
    status = component_status(component_id, component, root=root)
    if status["status"] == "error":
        raise ResidentHomeError(f"{component_id}: {status['error']}")
    stamp = _now().isoformat()
    commit = current_commit(root)
    dirty = worktree_dirty(root)
    reviewer = actor or current_actor(root)
    component["reviewed"] = {
        "fingerprint": status["fingerprint"],
        "file_hashes": status["file_hashes"],
        "commit": commit,
        "revision": f"{commit}-dirty" if dirty and commit else commit,
        "worktree_dirty": dirty,
        "reviewed_at": stamp,
        "reviewed_by": reviewer,
    }
    _write_json(manifest_path, data)
    event = None
    if not no_impact:
        event = {
            "week": week_key(_now()),
            "component": component_id,
            "title": component.get("title") or component_id,
            "summary": summary.strip(),
            "impact": impact.strip(),
            "commit": commit,
            "revision": f"{commit}-dirty" if dirty and commit else commit,
            "worktree_dirty": dirty,
            "created_at": stamp,
            "created_by": reviewer,
        }
        _append_change(changes_path, event)
    return {"component": component_id, "reviewed": component["reviewed"], "event": event}


def ack_shared_components(
    *,
    manifest_path: Path = MANIFEST_PATH,
    root: Path = ROOT,
    actor: str | None = None,
) -> dict[str, Any]:
    """Acknowledge components whose only changes live in shared source files.

    A file is "shared" when at least two components claim it: touching it
    fans review_required out to every owner even though most of them saw no
    behavior change of their own. This records the no-impact reviews for all
    such components in one pass and reports what was acknowledged, so the
    caller confirms one informed summary instead of rubber-stamping each
    component blind. Components with changes in files they own exclusively
    keep requiring a full ``review``.
    """
    data = load_manifest(manifest_path)
    owners = source_owner_map(data, root)
    stamp = _now().isoformat()
    commit = current_commit(root)
    dirty = worktree_dirty(root)
    reviewer = actor or current_actor(root)
    acked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    shared_files: dict[str, list[str]] = {}
    for component_id, component in data["components"].items():
        status = component_status(component_id, component, root=root)
        if status["status"] == "error":
            raise ResidentHomeError(f"{component_id}: {status['error']}")
        if status["status"] == "ok":
            continue
        changed = status.get("changed_files")
        if changed is None:
            skipped.append(
                {
                    "id": component_id,
                    "reason": "last review has no per-file baseline; use review once to record it",
                }
            )
            continue
        exclusive = [
            relative for relative in changed if len(owners.get(relative) or []) < 2
        ]
        if not changed or exclusive:
            skipped.append(
                {
                    "id": component_id,
                    "reason": "changes in files owned by this component need a full review",
                    "exclusive_files": exclusive,
                }
            )
            continue
        component["reviewed"] = {
            "fingerprint": status["fingerprint"],
            "file_hashes": status["file_hashes"],
            "commit": commit,
            "revision": f"{commit}-dirty" if dirty and commit else commit,
            "worktree_dirty": dirty,
            "reviewed_at": stamp,
            "reviewed_by": reviewer,
        }
        for relative in changed:
            shared_files.setdefault(relative, list(owners.get(relative) or []))
        acked.append({"id": component_id, "changed_files": changed})
    if acked:
        _write_json(manifest_path, data)
    return {"acked": acked, "skipped": skipped, "shared_files": shared_files}


def _describe_working_change(relative: str, root: Path = ROOT) -> str:
    """Best-effort one-line context for what changed in a file."""
    numstat = _git("diff", "HEAD", "--numstat", "--", relative, root=root)
    if numstat:
        added, removed, _ = numstat.split("\t", 2)
        return f"+{added}/-{removed} uncommitted"
    last = _git("log", "-1", "--format=%h %s", "--", relative, root=root)
    return f"committed · {last}" if last else "changed"


def load_changes(path: Path = CHANGES_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResidentHomeError(f"invalid change record at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict) or not value.get("week"):
            raise ResidentHomeError(f"invalid change record at {path}:{line_number}")
        events.append(value)
    return events


def changes_by_week(path: Path = CHANGES_PATH) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in load_changes(path):
        grouped.setdefault(str(event["week"]), []).append(event)
    return dict(sorted(grouped.items(), reverse=True))


def format_weekly_report(grouped: dict[str, list[dict[str, Any]]]) -> str:
    """Render a resident-readable report with a stable impact line."""
    lines: list[str] = []
    for week, events in grouped.items():
        lines.append(f"{week} · {len(events)} 条变化")
        for event in events:
            lines.append(f"- {event.get('title')}: {event.get('summary')}")
            lines.append(f"  影响：{event.get('impact') or ''}")
    return "\n".join(lines)


def home_overview(
    *,
    manifest_path: Path = MANIFEST_PATH,
    changes_path: Path = CHANGES_PATH,
) -> dict[str, Any]:
    """Return the cheap, context-safe summary of the generated home book."""
    manifest = load_manifest(manifest_path)
    last_confirmed = max(
        (
            str((component.get("reviewed") or {}).get("reviewed_at") or "")
            for component in manifest["components"].values()
        ),
        default="",
    )
    grouped = changes_by_week(changes_path)
    current_week = week_key()
    return {
        "current_week": current_week,
        "current_week_changes": len(grouped.get(current_week, [])),
        "last_confirmed_at": last_confirmed,
    }


def home_snapshot(
    *,
    manifest_path: Path = MANIFEST_PATH,
    changes_path: Path = CHANGES_PATH,
    root: Path = ROOT,
    runtime_config: Any = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    statuses = check_manifest(manifest, root=root)
    reviewed = [
        (status.get("reviewed") or {})
        for status in statuses
        if status.get("status") != "error"
    ]
    last_reviewed = max(
        (str(item.get("reviewed_at") or "") for item in reviewed),
        default="",
    )
    grouped = changes_by_week(changes_path)
    current_week = week_key()
    return {
        "live": {
            "commit": current_commit(root),
            "revision": current_revision(root),
            "worktree_dirty": worktree_dirty(root),
            "observed_at": _now().isoformat(),
            "last_confirmed_at": last_reviewed,
            "current_week": current_week,
            "current_week_changes": len(grouped.get(current_week, [])),
        },
        "components": [
            {
                "id": status["id"],
                "title": status["title"],
                "status": status["status"],
                "summary": manifest["components"][status["id"]].get("summary", ""),
                "core": manifest["components"][status["id"]].get("core", []),
                "resident_effect": manifest["components"][status["id"]].get("resident_effect", ""),
                "config_keys": manifest["components"][status["id"]].get("config_keys", []),
                "config": {
                    key: getattr(runtime_config, key, None)
                    for key in manifest["components"][status["id"]].get("config_keys", [])
                    if runtime_config is not None and hasattr(runtime_config, key)
                },
                # file_hashes is maintenance bookkeeping, not resident-facing.
                "reviewed": {
                    key: value
                    for key, value in (status.get("reviewed") or {}).items()
                    if key != "file_hashes"
                },
            }
            for status in statuses
        ],
        "changes": grouped,
    }


def _format_line_endings(report: dict[str, Any]) -> list[str]:
    """Line-ending lines for `check`, most actionable first."""
    if not report.get("checked"):
        # Printing nothing here reads exactly like a clean check, which is the one
        # thing this must not do: a guard that quietly stops guarding is worse than
        # no guard, because everyone downstream keeps trusting it.
        return ["[line endings] skipped (no git) — this check cannot see line endings here"]
    offenders = report.get("files") or []
    if not offenders:
        return []
    pending = report.get("pending") or []
    lines: list[str] = []
    if pending:
        lines.append(
            f"[line endings] {len(pending)} file(s) you are about to commit are not LF: "
            + ", ".join(pending[:6])
            + (f" … +{len(pending) - 6}" if len(pending) > 6 else "")
            + " — normalize before reviewing: sed -i 's/\\r$//' <path>"
        )
    inherited = [item["path"] for item in offenders if not item["pending"]]
    if inherited:
        lines.append(
            f"[line endings] {len(inherited)} other tracked file(s) carry non-LF endings "
            "from earlier sessions (commits stay LF via .gitattributes; normalize when you "
            "next touch them): "
            + ", ".join(inherited[:4])
            + (f" … +{len(inherited) - 4}" if len(inherited) > 4 else "")
        )
    return lines


def _print_check(
    statuses: Iterable[dict[str, Any]],
    *,
    as_json: bool = False,
    line_endings: dict[str, Any] | None = None,
) -> int:
    records = list(statuses)
    report = line_endings or {"checked": False, "files": []}
    if as_json:
        print(
            json.dumps(
                {"components": records, "line_endings": report},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for record in records:
            if record["status"] == "ok":
                print(f"[ok] {record['id']} / {record['title']}")
            elif record["status"] == "error":
                print(f"[error] {record['id']}: {record['error']}")
            else:
                changed = record.get("changed_files")
                if changed is None:
                    detail = "sources changed since last review"
                else:
                    shared = set(record.get("shared_changed_files") or [])
                    names = [
                        f"{relative}*" if relative in shared else relative
                        for relative in changed
                    ]
                    detail = f"{len(changed)} changed: " + ", ".join(names[:6])
                    if len(names) > 6:
                        detail += f" … +{len(names) - 6}"
                    if shared:
                        detail += " (*=shared, ack-shared applies if all are *)"
                print(f"[review required] {record['id']} / {record['title']} ({detail})")
        for line in _format_line_endings(report):
            print(line)
    if any(record["status"] != "ok" for record in records):
        return 1
    return 1 if report.get("pending") else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain the resident-facing home map and change ledger.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check whether mapped source files need resident review.")
    check.add_argument("--json", action="store_true", dest="as_json")

    bootstrap = subparsers.add_parser("bootstrap", help="Record the current source fingerprints without a change entry.")
    bootstrap.add_argument("--actor", default="")

    review = subparsers.add_parser("review", help="Review one component and optionally append a resident change.")
    review.add_argument("component")
    review.add_argument("--summary", default="")
    review.add_argument("--impact", default="")
    review.add_argument("--no-impact", action="store_true")
    review.add_argument("--actor", default="")

    ack_shared = subparsers.add_parser(
        "ack-shared",
        help="No-impact ack for every component whose only changes are in shared source files.",
    )
    ack_shared.add_argument("--actor", default="")

    report = subparsers.add_parser("report", help="Print the weekly resident change ledger.")
    report.add_argument("--week", default="")
    report.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return _print_check(
                check_manifest(),
                as_json=args.as_json,
                line_endings=working_tree_line_endings(),
            )
        if args.command == "bootstrap":
            bootstrap_manifest(actor=args.actor or None)
            print("resident home fingerprints bootstrapped")
            return 0
        if args.command == "review":
            result = review_component(
                args.component,
                summary=args.summary,
                impact=args.impact,
                no_impact=args.no_impact,
                actor=args.actor or None,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "ack-shared":
            result = ack_shared_components(actor=args.actor or None)
            for relative, owner_ids in sorted(result["shared_files"].items()):
                print(f"[shared] {relative} ← {'/'.join(owner_ids)} · {_describe_working_change(relative)}")
            for item in result["acked"]:
                print(f"[acked] {item['id']} ({len(item['changed_files'])} shared file(s))")
            for item in result["skipped"]:
                extra = ""
                if item.get("exclusive_files"):
                    extra = " — " + ", ".join(item["exclusive_files"])
                print(f"[needs review] {item['id']}: {item['reason']}{extra}")
            if not result["acked"] and not result["skipped"]:
                print("nothing to acknowledge — all components ok")
            return 1 if result["skipped"] else 0
        grouped = changes_by_week()
        if args.week:
            grouped = {args.week: grouped.get(args.week, [])}
        if args.as_json:
            print(json.dumps(grouped, ensure_ascii=False, indent=2))
        else:
            print(format_weekly_report(grouped))
        return 0
    except ResidentHomeError as exc:
        print(f"resident-home: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
