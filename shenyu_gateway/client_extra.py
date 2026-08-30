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

# 过期图占位块的线上标记。PWA 只在本机淘汰掉一张图之后送它，块里只有图片字节的
# sha256，没有任何字节。三个地方必须逐字一致，所以住在这里：PWA 的
# `pwa/src/api/client.ts::EXPIRED_IMAGE_MARKER`、裁剪
# (`context_layers.trim_client_image_blocks`)、以及历史归一化
# (`context_window`)。
#
# 刻意与 `context_window` 的 `shenyu_history_image` 分开：那个标记的 fingerprint
# 是 JSON 块的哈希，只服务血统日志；这个是图片字节的哈希，用来在相册里认出这张图。
EXPIRED_IMAGE_MARKER = "shenyu_expired_image"

# 过期图替换文本的固定前缀。带前缀是必须的，不是装饰：历史归一化要能认出
# 「这里是一张过期图的占位」并把它归一化掉，否则沈予每次换一句描述都会让
# 归一化结果变化、被分支检测误判成 branch，白扔掉整个 prompt cache epoch。
EXPIRED_IMAGE_NOTE_PREFIX = "圆圆发来的照片我已经看过"


def expired_image_fingerprint(block: object) -> str:
    """从一个过期图占位块里取出图片字节指纹；不是这种块就返回空串。"""
    if not isinstance(block, dict):
        return ""
    source = block.get("source")
    if not isinstance(source, dict):
        return ""
    if str(source.get("type") or "") != EXPIRED_IMAGE_MARKER:
        return ""
    return str(source.get("fingerprint") or "").strip()


def expired_image_note_text(note: str = "", mood: str = "") -> str:
    """沈予存过这张图时，占位换成他自己写的话。

    形状固定为 `前缀。——他的话`：前缀让归一化认得出这是过期图占位，
    后半是他自己的措辞，不概括、不改写。
    """
    parts = [part.strip() for part in (note, mood) if str(part or "").strip()]
    if not parts:
        return f"{EXPIRED_IMAGE_NOTE_PREFIX}。"
    return f"{EXPIRED_IMAGE_NOTE_PREFIX}。——{'｜'.join(parts)}"


def is_expired_image_note(text: str) -> bool:
    """这段文字是不是过期图占位（不论后面跟着谁的话）。"""
    return str(text or "").strip().startswith(EXPIRED_IMAGE_NOTE_PREFIX)

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
