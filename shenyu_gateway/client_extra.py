from __future__ import annotations

"""Shared recognition of client-injected per-message extra state.

Two client shapes carry device/state context inside user messages:

- Operit appends ``<attachment id="message_insert_extra_bundle_...">`` XML
  blocks with device state.
- The PWA appends a tail status suffix such as
  ``【26/07 周日 14:30 · 第140天 · 🔋80%⚡ · 邵阳 霾 25℃】`` (time and day
  segments always present, battery/weather segments optional).

This module is the single home for both patterns so trimming, archiving,
history normalization, and recall-query cleaning cannot drift apart.
It must stay free of package-internal imports (regex + helpers only).
"""

import re

CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b"
    r"(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)"
    r"[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)

# Cross-client contract: the PWA appends the status suffix to the very end of
# the user text, so the pattern is tail-anchored on purpose — ordinary
# 【...】 usage mid-message must never match.
PWA_STATUS_SUFFIX_RE = re.compile(
    r"\s*【\d{1,2}/\d{1,2}\s*周[一二三四五六日]\s*\d{1,2}:\d{2}[^【】]*】\s*$"
)


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
