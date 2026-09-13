#!/usr/bin/env python3
"""Fast pre-handoff verification for the live owner project map."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shenyu_gateway.project_map import project_map_snapshot  # noqa: E402


def main() -> int:
    snapshot = project_map_snapshot(root=ROOT)
    warnings = snapshot.get("warnings") or []
    if warnings:
        for warning in warnings:
            print(f"[warning] {warning}")
        return 1
    summary = snapshot["summary"]
    print(
        f"[ok] map verified · {summary['zone_count']} zones · "
        f"{summary['component_count']} components · {summary['delivery_count']} deliveries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
