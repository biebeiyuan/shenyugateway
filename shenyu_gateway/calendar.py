from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .runtime import parse_ts


def _utc_day_bounds(day_key: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _week_bounds(week_key: str) -> tuple[datetime, datetime]:
    year_str, week_str = week_key.split("-W", 1)
    start = datetime.fromisocalendar(int(year_str), int(week_str), 1).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    return start, end


def _month_bounds(month_key: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(month_key, "%Y-%m").replace(day=1, tzinfo=timezone.utc)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def period_bounds(period_type: str, period_key: str) -> tuple[datetime, datetime]:
    if period_type == "day":
        return _utc_day_bounds(period_key)
    if period_type == "week":
        return _week_bounds(period_key)
    if period_type == "month":
        return _month_bounds(period_key)
    raise ValueError(f"Unsupported period_type: {period_type}")


def default_period_key(period_type: str, now_dt: Optional[datetime] = None) -> str:
    now_dt = now_dt or datetime.now(timezone.utc)
    if period_type == "day":
        return now_dt.strftime("%Y-%m-%d")
    if period_type == "week":
        year, week, _ = now_dt.isocalendar()
        return f"{year}-W{week:02d}"
    if period_type == "month":
        return now_dt.strftime("%Y-%m")
    raise ValueError(f"Unsupported period_type: {period_type}")


def period_key_from_date(period_type: str, day_key: str) -> str:
    """Convert the natural YYYY-MM-DD tool input into the selected calendar key."""
    day = datetime.strptime((day_key or "").strip(), "%Y-%m-%d")
    if period_type == "day":
        return day.strftime("%Y-%m-%d")
    if period_type == "week":
        iso = day.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if period_type == "month":
        return day.strftime("%Y-%m")
    raise ValueError(f"Unsupported period_type: {period_type}")


def month_grid(month_key: str) -> list[dict[str, Any]]:
    start, end = _month_bounds(month_key)
    first = start - timedelta(days=start.weekday())
    last_day = end - timedelta(days=1)
    last = last_day + timedelta(days=(6 - last_day.weekday()))
    items: list[dict[str, Any]] = []
    current = first
    while current <= last:
        items.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "day": current.day,
                "in_month": current.month == start.month,
                "week_key": f"{current.isocalendar().year}-W{current.isocalendar().week:02d}",
                "month_key": current.strftime("%Y-%m"),
            }
        )
        current += timedelta(days=1)
    return items


def latest_page_by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row.get('period_type')}::{row.get('period_key')}"
        prev = latest.get(key)
        if not prev:
            latest[key] = row
            continue
        prev_ts = parse_ts(prev.get("updated_at") or prev.get("created_at") or "")
        row_ts = parse_ts(row.get("updated_at") or row.get("created_at") or "")
        if row_ts and (not prev_ts or row_ts >= prev_ts):
            latest[key] = row
    return latest
