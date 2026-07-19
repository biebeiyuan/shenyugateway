from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "resident_home_manifest.json"
CHANGES_PATH = ROOT / "resident_home_changes.jsonl"
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


class ResidentHomeError(ValueError):
    """Raised when the resident-home mapping cannot be trusted."""


def _now() -> datetime:
    return datetime.now(LOCAL_ZONE).replace(microsecond=0)


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


def component_fingerprint(component: dict[str, Any], root: Path = ROOT) -> str:
    files = _source_files(component, root)
    if not files:
        raise ResidentHomeError("source_globs did not match any files")
    digest = hashlib.sha256()
    for relative, path in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        # Mapped sources are text files, and this repo is edited from both
        # WSL and Windows clients. Normalize line endings so a checkout does
        # not create a false resident-review alarm.
        normalized = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(normalized)
        digest.update(b"\0")
    return digest.hexdigest()


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
    fingerprint = component_fingerprint(component, root)
    reviewed = component.get("reviewed") or {}
    reviewed_fingerprint = str(reviewed.get("fingerprint") or "")
    return {
        "id": component_id,
        "title": component.get("title") or component_id,
        "status": "ok" if reviewed_fingerprint == fingerprint else "review_required",
        "fingerprint": fingerprint,
        "reviewed_fingerprint": reviewed_fingerprint,
        "files": [relative for relative, _ in files],
        "reviewed": reviewed,
    }


def check_manifest(
    manifest: dict[str, Any] | None = None,
    *,
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    data = manifest or load_manifest(root / "resident_home_manifest.json")
    return [
        component_status(component_id, component, root=root)
        for component_id, component in data["components"].items()
    ]


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
                "reviewed": status.get("reviewed", {}),
            }
            for status in statuses
        ],
        "changes": grouped,
    }


def _print_check(statuses: Iterable[dict[str, Any]], *, as_json: bool = False) -> int:
    records = list(statuses)
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for record in records:
            if record["status"] == "ok":
                print(f"[ok] {record['id']} / {record['title']}")
            elif record["status"] == "error":
                print(f"[error] {record['id']}: {record['error']}")
            else:
                print(
                    f"[review required] {record['id']} / {record['title']} "
                    f"({len(record.get('files') or [])} source files changed)"
                )
    return 1 if any(record["status"] != "ok" for record in records) else 0


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

    report = subparsers.add_parser("report", help="Print the weekly resident change ledger.")
    report.add_argument("--week", default="")
    report.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return _print_check(check_manifest(), as_json=args.as_json)
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
        grouped = changes_by_week()
        if args.week:
            grouped = {args.week: grouped.get(args.week, [])}
        if args.as_json:
            print(json.dumps(grouped, ensure_ascii=False, indent=2))
        else:
            for week, events in grouped.items():
                print(f"{week} · {len(events)} 条变化")
                for event in events:
                    print(f"- {event.get('title')}: {event.get('summary')}（影响：{event.get('impact')}）")
        return 0
    except ResidentHomeError as exc:
        print(f"resident-home: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
