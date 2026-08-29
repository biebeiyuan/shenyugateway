from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .resident_home import current_actor, current_commit


ROOT = Path(__file__).resolve().parent.parent
DELIVERY_LOG_PATH = ROOT / "project_delivery_log.jsonl"
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")

DELIVERY_KINDS = {"feature", "fix", "experience", "operations", "architecture"}
DELIVERY_STATUSES = {"verified_local", "pushed", "deployed", "device_verified"}


class ProjectDeliveryError(ValueError):
    """Raised when a project delivery record cannot be trusted."""


def _required_text(value: Any, field: str, *, location: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProjectDeliveryError(f"{location}: {field} is required")
    return text


ABANDONED_FIELDS = ("what", "why", "cost")
# One line each, deliberately short. The point of this field is to stop the next
# agent from re-walking a road that was already measured and rejected, which needs
# three facts and nothing else. Room for a paragraph invites a work diary, and the
# `lesson` field already exists for anything worth carrying forward.
ABANDONED_FIELD_LIMIT = 120


def _abandoned_line(value: Any, field: str, *, location: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProjectDeliveryError(f"{location}: abandoned.{field} is required")
    if "\n" in text or "\r" in text:
        raise ProjectDeliveryError(f"{location}: abandoned.{field} must be a single line")
    if len(text) > ABANDONED_FIELD_LIMIT:
        raise ProjectDeliveryError(
            f"{location}: abandoned.{field} must be at most {ABANDONED_FIELD_LIMIT} characters "
            f"(got {len(text)}) — record the fact, not the process"
        )
    return text


def _abandoned_list(value: Any, *, location: str) -> list[dict[str, str]]:
    """Roads measured and rejected during this delivery, three facts each.

    Shape is fixed: what was abandoned, one sentence of why, roughly what it cost.
    No fourth key, no multi-line prose. A future agent reads this to skip work, so
    anything that is not one of those three facts belongs in `lesson` or nowhere.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectDeliveryError(f"{location}: abandoned must be an array")
    entries: list[dict[str, str]] = []
    for index, item in enumerate(value):
        where = f"{location}: abandoned[{index}]"
        if not isinstance(item, dict):
            raise ProjectDeliveryError(f"{where} must be an object with {', '.join(ABANDONED_FIELDS)}")
        extra = sorted(set(item) - set(ABANDONED_FIELDS))
        if extra:
            raise ProjectDeliveryError(f"{where}: unsupported field(s) {', '.join(extra)}")
        entries.append(
            {field: _abandoned_line(item.get(field), field, location=where) for field in ABANDONED_FIELDS}
        )
    return entries


def _text_list(value: Any, field: str, *, location: str, required: bool = False) -> list[str]:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, list):
        items = value
    else:
        raise ProjectDeliveryError(f"{location}: {field} must be a string array")
    result = [str(item or "").strip() for item in items if str(item or "").strip()]
    if required and not result:
        raise ProjectDeliveryError(f"{location}: {field} must contain at least one item")
    return result


def normalize_delivery(value: Any, *, location: str = "delivery") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectDeliveryError(f"{location}: record must be an object")

    delivery_id = _required_text(value.get("id"), "id", location=location)
    completed_at = _required_text(value.get("completed_at"), "completed_at", location=location)
    try:
        parsed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectDeliveryError(f"{location}: completed_at must be ISO-8601") from exc
    if parsed_at.utcoffset() is None:
        raise ProjectDeliveryError(f"{location}: completed_at must include a timezone")

    kind = _required_text(value.get("kind"), "kind", location=location)
    if kind not in DELIVERY_KINDS:
        raise ProjectDeliveryError(f"{location}: unsupported kind {kind!r}")
    status = _required_text(value.get("status"), "status", location=location)
    if status not in DELIVERY_STATUSES:
        raise ProjectDeliveryError(f"{location}: unsupported status {status!r}")

    return {
        "id": delivery_id,
        "completed_at": parsed_at.isoformat(),
        "title": _required_text(value.get("title"), "title", location=location),
        "product": _required_text(value.get("product"), "product", location=location),
        "kind": kind,
        "summary": _required_text(value.get("summary"), "summary", location=location),
        "touchpoint": _required_text(value.get("touchpoint"), "touchpoint", location=location),
        "why": _required_text(value.get("why"), "why", location=location),
        "status": status,
        "verification": _text_list(value.get("verification"), "verification", location=location, required=True),
        "paths": _text_list(value.get("paths"), "paths", location=location, required=True),
        "docs": _text_list(value.get("docs"), "docs", location=location),
        "abandoned": _abandoned_list(value.get("abandoned"), location=location),
        "commit": str(value.get("commit") or "").strip(),
        "lesson": str(value.get("lesson") or "").strip(),
        "debug_ref": str(value.get("debug_ref") or "").strip(),
        "recorded_by": str(value.get("recorded_by") or "").strip(),
    }


def load_delivery_log(path: Path = DELIVERY_LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    deliveries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProjectDeliveryError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        delivery = normalize_delivery(raw, location=f"{path}:{line_number}")
        if delivery["id"] in seen:
            raise ProjectDeliveryError(f"{path}:{line_number}: duplicate id {delivery['id']!r}")
        seen.add(delivery["id"])
        deliveries.append(delivery)
    return sorted(deliveries, key=lambda item: item["completed_at"], reverse=True)


def append_delivery(record: dict[str, Any], path: Path = DELIVERY_LOG_PATH) -> dict[str, Any]:
    delivery = normalize_delivery(record)
    existing = {item["id"] for item in load_delivery_log(path)}
    if delivery["id"] in existing:
        raise ProjectDeliveryError(f"duplicate id {delivery['id']!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(delivery, ensure_ascii=False, separators=(",", ":")) + "\n")
    return delivery


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain the owner-facing project delivery log.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Validate every delivery record.")
    list_parser = subparsers.add_parser("list", help="Print recent delivery records.")
    list_parser.add_argument("--limit", type=int, default=12)

    record = subparsers.add_parser("record", help="Append one coherent delivered outcome.")
    record.add_argument("--id", required=True)
    record.add_argument("--title", required=True)
    record.add_argument("--product", required=True)
    record.add_argument("--kind", choices=sorted(DELIVERY_KINDS), required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--touchpoint", required=True)
    record.add_argument("--why", required=True)
    record.add_argument("--status", choices=sorted(DELIVERY_STATUSES), default="verified_local")
    record.add_argument("--verification", action="append", required=True)
    record.add_argument("--path", dest="paths", action="append", required=True)
    record.add_argument("--doc", dest="docs", action="append", default=[])
    record.add_argument(
        "--abandoned",
        dest="abandoned",
        action="append",
        default=[],
        metavar="放弃了什么|为什么|花了多少",
        help=(
            "A road measured and rejected, as three `|`-separated one-liners: what was "
            "abandoned, one sentence why, roughly the cost. Repeatable."
        ),
    )
    record.add_argument("--completed-at", default="")
    record.add_argument("--commit", default="")
    record.add_argument("--lesson", default="")
    record.add_argument("--debug-ref", default="")
    record.add_argument("--recorded-by", default="")
    return parser


def parse_abandoned_argument(value: str) -> dict[str, str]:
    """Split one `--abandoned` argument into the three fields it must carry."""
    parts = [part.strip() for part in str(value).split("|")]
    if len(parts) != len(ABANDONED_FIELDS):
        raise ProjectDeliveryError(
            "--abandoned takes exactly three `|`-separated parts "
            f"(放弃了什么|为什么|花了多少), got {len(parts)}: {value!r}"
        )
    return dict(zip(ABANDONED_FIELDS, parts))


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(_parser().parse_args(argv))
    except ProjectDeliveryError as exc:
        # A mis-shaped `--abandoned` is a typo in a long command line, not a bug
        # worth a traceback.
        print(f"project-delivery: {exc}")
        return 2


def _run(args: argparse.Namespace) -> int:
    if args.command == "check":
        deliveries = load_delivery_log()
        print(f"[ok] {len(deliveries)} project deliveries")
        return 0
    if args.command == "list":
        for delivery in load_delivery_log()[: max(0, args.limit)]:
            print(
                f"{delivery['completed_at'][:10]} · {delivery['product']} · "
                f"{delivery['title']} [{delivery['status']}]"
            )
        return 0

    record = {
        "id": args.id,
        "completed_at": args.completed_at or datetime.now(LOCAL_ZONE).replace(microsecond=0).isoformat(),
        "title": args.title,
        "product": args.product,
        "kind": args.kind,
        "summary": args.summary,
        "touchpoint": args.touchpoint,
        "why": args.why,
        "status": args.status,
        "verification": args.verification,
        "paths": args.paths,
        "docs": args.docs,
        "abandoned": [parse_abandoned_argument(item) for item in args.abandoned],
        "commit": args.commit or current_commit(),
        "lesson": args.lesson,
        "debug_ref": args.debug_ref,
        "recorded_by": args.recorded_by or current_actor(),
    }
    delivery = append_delivery(record)
    print(f"[recorded] {delivery['id']} · {delivery['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
