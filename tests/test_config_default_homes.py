"""A config default must not have a second home.

`getattr(cfg, "field", 5)` reads like a harmless safety net, but it is a copy of
a number whose real home is `config.py`. The copy is unreachable in production
(the field always exists on `RuntimeConfig`), so when the real default moves the
copy goes stale in total silence — and it stays reachable in tests, where fake
`SimpleNamespace` configs omit fields. That is the worst shape available: dead in
production, load-bearing in tests, and drifting.

Three had already drifted when this test was written: `star_min_score` (0.18 vs
0.008, a fallback left behind by the RRF v4 rescale), `mem_note_default_cooldown_hours`
(72 vs 12) and `calendar_context_day_offset` (0 vs 2).
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "shenyu_gateway" / "config.py"

_CONFIG_DEFAULT_RE = re.compile(
    r"self\.(\w+)\s*:\s*\w+\s*=\s*_env_(?:float|int)\(\s*\n?\s*\"[A-Z_0-9]+\",\s*\n?\s*(-?[\d.]+)"
)
_FALLBACK_RE = re.compile(
    r"(?:_cfg_float|_cfg_int|_safe_float|_safe_int|getattr)\(\s*(?:self\.cfg|cfg)\s*,\s*"
    r"\"(\w+)\"\s*,\s*(-?[\d.]+)"
)


def _config_defaults() -> dict[str, float]:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    return {name: float(value) for name, value in _CONFIG_DEFAULT_RE.findall(text)}


def _fallback_sites() -> list[tuple[str, int, str, float]]:
    sites: list[tuple[str, int, str, float]] = []
    for path in sorted((ROOT / "shenyu_gateway").rglob("*.py")):
        if path.name == "config.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for name, value in _FALLBACK_RE.findall(line):
                sites.append((str(path.relative_to(ROOT)), lineno, name, float(value)))
    return sites


def test_numeric_config_fallbacks_match_the_config_default():
    defaults = _config_defaults()
    drifted = [
        f"{path}:{lineno} {name}: fallback {value} != config.py default {defaults[name]}"
        for path, lineno, name, value in _fallback_sites()
        if name in defaults and value != defaults[name]
    ]
    assert not drifted, "a config default grew a second, divergent home:\n" + "\n".join(drifted)


def test_the_scan_actually_reaches_the_known_fallback_sites():
    # Without this, a broken regex would make the test above pass by finding
    # nothing at all — the failure mode that makes a guard worthless.
    defaults = _config_defaults()
    assert len(defaults) > 60, f"only parsed {len(defaults)} config defaults"
    matched = {name for _, _, name, _ in _fallback_sites() if name in defaults}
    assert "star_min_score" in matched
    assert "mem_note_default_cooldown_hours" in matched
    assert "calendar_context_day_offset" in matched
