from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

logger = logging.getLogger("shenyu-gateway")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_ts() -> int:
    return int(now().timestamp())


def iso_now() -> str:
    return now().isoformat()


def dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def mask(value: str, keep: int = 8) -> str:
    if len(value) <= keep + 4:
        return "****"
    return value[:keep] + "****"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def persist_env(updates: dict[str, Any]) -> None:
    if not updates:
        return

    existing = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines = existing.splitlines()
    remaining = {key: env_value(value) for key, value in updates.items()}
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue

        key = line.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    if remaining and new_lines and new_lines[-1].strip():
        new_lines.append("")
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
