from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH, override=True)

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


# 我们过的是 Asia/Shanghai 的日子。now() 只给 UTC，所以任何"今天""几天前"
# 的判断都得先落到这个时区，否则 UTC 的 8 点前会算成前一天。
LOCAL_DAY_TZ = timezone(timedelta(hours=8))


def local_today() -> date:
    """Return today's date in Asia/Shanghai."""
    return now().astimezone(LOCAL_DAY_TZ).date()


def parse_local_date(value: Any) -> Optional[date]:
    """Parse a YYYY-MM-DD day (or the day part of a timestamp) into a date."""
    if isinstance(value, datetime):
        return value.astimezone(LOCAL_DAY_TZ).date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def local_day_of(value: Optional[str]) -> Optional[date]:
    """Return the Asia/Shanghai calendar day of a stored timestamp."""
    dt = parse_ts(value)
    return dt.astimezone(LOCAL_DAY_TZ).date() if dt else None


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


def env_file_value(value: Any) -> str:
    text = env_value(value)
    if "\n" in text or "\r" in text:
        return json.dumps(text, ensure_ascii=False)
    return text


def persist_env(updates: dict[str, Any], *, store: Any = None) -> None:
    if not updates:
        return

    existing = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines = existing.splitlines()
    remaining = {key: env_file_value(value) for key, value in updates.items()}
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

    for key, value in updates.items():
        os.environ[key] = env_value(value)

    if store is not None:
        store.save_config_overrides({key: env_value(value) for key, value in updates.items()})
