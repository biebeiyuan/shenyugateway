#!/usr/bin/env python3
"""CLI wrapper for the document co-change observation tool."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shenyu_gateway.doc_touchpoints import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
