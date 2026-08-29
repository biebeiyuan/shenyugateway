from __future__ import annotations

"""Shared recognition of client-injected per-message extra state.

Two client shapes carry device/state context inside user messages:

- Operit appends ``<attachment id="message_insert_extra_bundle_...">`` XML
  blocks with device state.
- The PWA appends a tail status suffix such as
  ``【26/07 周日 14:30 · 第140天 · 🔋80%⚡ · 邵阳 霾 25°C】`` (time and day
  segments always present, battery/weather segments optional).

This module is the single home for both patterns so trimming, archiving,
history normalization, and recall-query cleaning cannot drift apart.
It must stay free of package-internal imports (regex + helpers only).
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b"
    r"(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)"
    r"[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)

# Cross-client contract: the PWA appends the status suffix to the very end of
# the user text, so the pattern is tail-anchored on purpose — ordinary
# 【...】 usage mid-message must never match. The named groups only capture;
# matching stays byte-identical to the JS twin in pwa/src/meta/statusSuffix.ts.
PWA_STATUS_SUFFIX_RE = re.compile(
    r"\s*【(?P<day>\d{1,2})/(?P<month>\d{1,2})\s*周[一二三四五六日]\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<rest>[^【】]*)】\s*$"
)

# 第N天 segment inside the suffix. 第1天 = 2026-03-09 (Asia/Shanghai natural
# day) — twin of DAY_ONE_UTC in pwa/src/meta/days.ts / admin/src/utils/days.ts.
PWA_STATUS_DAY_SEGMENT_RE = re.compile(r"第(?P<n>\d+)天")
PWA_DAY_ONE = (2026, 3, 9)

# The one local copy of the +08:00 offset. Everywhere else in the package imports
# runtime.LOCAL_DAY_TZ, but this module's contract (see the docstring) is to stay
# importable with nothing package-internal behind it, so it keeps its own.
_CST = timezone(timedelta(hours=8))


def parse_pwa_status_suffix_time(text: str, *, now: Optional[datetime] = None) -> Optional[datetime]:
    """Recover the client-local send time from a PWA status suffix.

    The 第N天 segment carries the year (DD/MM alone does not), so the date is
    anchored on it. When 第N天 is missing — the contract says it never is, but
    old or hand-edited messages may drift — fall back to DD/MM with the year
    that lands the date closest to ``now``. Returns an aware UTC datetime,
    or None when there is no suffix or its fields are not a real moment.
    """
    match = PWA_STATUS_SUFFIX_RE.search(text or "")
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    day_seg = PWA_STATUS_DAY_SEGMENT_RE.search(match.group("rest") or "")
    try:
        if day_seg:
            base = datetime(*PWA_DAY_ONE, tzinfo=_CST) + timedelta(days=int(day_seg.group("n")) - 1)
            stamped = base.replace(hour=hour, minute=minute)
        else:
            reference = (now or datetime.now(timezone.utc)).astimezone(_CST)
            day = int(match.group("day"))
            month = int(match.group("month"))
            candidates = []
            for year in (reference.year - 1, reference.year, reference.year + 1):
                try:
                    candidates.append(datetime(year, month, day, hour, minute, tzinfo=_CST))
                except ValueError:
                    continue
            if not candidates:
                return None
            stamped = min(candidates, key=lambda item: abs(item - reference))
    except (ValueError, OverflowError):
        # OverflowError: a corrupted/hand-edited 第N天 far beyond year 9999.
        return None
    return stamped.astimezone(timezone.utc)


def has_client_extra_text(text: str) -> bool:
    """True when the text carries an Operit bundle or the PWA status suffix."""
    if not text:
        return False
    return bool(
        CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE.search(text)
        or PWA_STATUS_SUFFIX_RE.search(text)
    )


def strip_pwa_status_suffix(text: str) -> tuple[str, int]:
    """Strip tail status suffixes repeatedly.

    The tail anchor only sees the outermost layer per pass, so stacked
    suffixes need a loop — the PWA's JS ``stripStatusSuffix`` loops the
    same way and the two sides must agree.
    Returns ``(cleaned_text, removed_count)``.
    """
    removed = 0
    while True:
        text, count = PWA_STATUS_SUFFIX_RE.subn("", text)
        if not count:
            return text, removed
        removed += count


def strip_client_extra_text(text: str) -> tuple[str, int]:
    """Remove bundle attachments and the PWA status suffix from one text.

    Attachments are stripped first: if a bundle trails the message, removing
    it can expose the PWA suffix as the new tail.
    Returns ``(cleaned_text, removed_segment_count)``.
    """
    cleaned, removed = CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE.subn("", text)
    cleaned, suffix_removed = strip_pwa_status_suffix(cleaned)
    removed += suffix_removed
    if not removed:
        return text, 0
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), removed
