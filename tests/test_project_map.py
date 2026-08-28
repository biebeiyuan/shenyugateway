import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _section(path: str, start: str, end: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    return text.split(start, 1)[1].split(end, 1)[0]


def _maintenance_map() -> str:
    return _section("README.md", "## Maintenance Map", "## Subsystem Guides")


def _expected_map_paths() -> set[str]:
    paths = {"gateway.py"}
    paths.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "shenyu_gateway").glob("*.py")
        if path.name != "__init__.py"
    )
    paths.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "admin" / "src" / "views").rglob("*")
        if path.suffix in {".ts", ".vue"} and not path.name.endswith(".spec.ts")
    )
    paths.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "admin" / "src" / "api").glob("*.ts")
        if not path.name.endswith(".spec.ts")
    )
    return paths


def _indexed_map_paths() -> set[str]:
    entries = set(re.findall(r"`([^`]+)`", _maintenance_map()))
    return {
        entry
        for entry in entries
        if entry == "gateway.py"
        or (
            entry.startswith("shenyu_gateway/")
            and entry.endswith(".py")
            and entry.count("/") == 1
        )
        or (
            entry.startswith("admin/src/views/")
            and Path(entry).suffix in {".ts", ".vue"}
        )
        or (
            entry.startswith("admin/src/api/")
            and Path(entry).suffix == ".ts"
        )
    }


def _current_doc_paths() -> set[str]:
    section = _section("DOCS_MAP.md", "## 现行文档", "## 地图同步边界")
    return set(re.findall(r"^\| `([^`]+)` \|", section, flags=re.MULTILINE))


def _system_zone_core_paths() -> set[str]:
    lines = (ROOT / "docs/architecture/SYSTEM_ZONES.md").read_text(
        encoding="utf-8"
    ).splitlines()
    paths: set[str] = set()
    in_core_files = False
    for line in lines:
        if line == "**核心文件**":
            in_core_files = True
            continue
        if in_core_files and (line.startswith("**") or line.startswith("#")):
            in_core_files = False
        if not in_core_files:
            continue
        match = re.fullmatch(r"- `([^`]+)`", line)
        if match:
            paths.add(match.group(1))
    return paths


def _path_or_glob_exists(entry: str) -> bool:
    if any(marker in entry for marker in "*?["):
        return any(ROOT.glob(entry))
    return (ROOT / entry).exists()


def test_readme_maintenance_map_covers_runtime_entry_files():
    missing = sorted(_expected_map_paths() - _indexed_map_paths())
    assert not missing, f"README Maintenance Map is missing: {missing}"


def test_readme_maintenance_map_has_no_stale_runtime_entry_files():
    stale = sorted(path for path in _indexed_map_paths() if not (ROOT / path).is_file())
    assert not stale, f"README Maintenance Map has stale paths: {stale}"


def test_docs_map_current_documents_exist():
    paths = _current_doc_paths()
    assert "DOCS_MAP.md" in paths, "DOCS_MAP current-document table was not parsed"
    missing = sorted(path for path in paths if not (ROOT / path).is_file())
    assert not missing, f"DOCS_MAP current documents are missing: {missing}"


def test_system_zones_core_paths_exist():
    paths = _system_zone_core_paths()
    assert "gateway.py" in paths, "SYSTEM_ZONES core-file sections were not parsed"
    missing = sorted(path for path in paths if not _path_or_glob_exists(path))
    assert not missing, f"SYSTEM_ZONES core paths are missing: {missing}"


def test_readme_maintenance_map_covers_runtime_packages():
    # Per-file coverage skips package internals, so every runtime package must
    # at least have a directory-level entry or it silently leaves the map.
    packages = {
        f"shenyu_gateway/{path.name}/"
        for path in (ROOT / "shenyu_gateway").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file() and path.name != "__pycache__"
    }
    entries = set(re.findall(r"`([^`]+)`", _maintenance_map()))
    missing = sorted(pkg for pkg in packages if pkg not in entries)
    assert not missing, f"README Maintenance Map is missing package entries: {missing}"


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()


def _live_docs() -> list[str]:
    # Dated snapshots under docs/history/ record what was true then; they are
    # deliberately allowed to name symbols that have since moved or gone.
    return [
        path
        for path in _tracked_files()
        if path.endswith(".md") and not path.startswith("docs/history/")
    ]


def _symbol_anchors(doc: str) -> set[tuple[str, str]]:
    text = (ROOT / doc).read_text(encoding="utf-8")
    return set(re.findall(r"`([\w./-]+\.(?:py|ts|vue))::([\w.]+)`", text))


def _resolve_named_file(reference: str, tracked: list[str]) -> str | None:
    """Docs name files by the shortest unambiguous suffix, not the full path."""
    if (ROOT / reference).is_file():
        return reference
    matches = [path for path in tracked if path.endswith("/" + reference)]
    return matches[0] if len(matches) == 1 else None


def _defines_symbol(path: str, symbol: str) -> bool:
    text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
    leaf = re.escape(symbol.rsplit(".", 1)[-1])
    return bool(
        re.search(rf"^\s*(?:async\s+def|def|class)\s+{leaf}\b", text, flags=re.MULTILINE)
        or re.search(rf"^\s*{leaf}\s*[:=]", text, flags=re.MULTILINE)
    )


def test_live_docs_symbol_anchors_still_resolve():
    # A `file.py::symbol` anchor is the one doc reference that names something
    # small enough to be moved or renamed without anyone noticing. Path-only
    # references are already covered by the map tests above; symbols are not.
    tracked = _tracked_files()
    if not tracked:  # No git available: nothing to verify against.
        return
    broken: dict[str, list[str]] = {}
    for doc in _live_docs():
        for reference, symbol in sorted(_symbol_anchors(doc)):
            path = _resolve_named_file(reference, tracked)
            if path is None:
                broken.setdefault(doc, []).append(f"{reference}::{symbol} (file not found)")
            elif not _defines_symbol(path, symbol):
                broken.setdefault(doc, []).append(f"{reference}::{symbol} (gone from {path})")
    assert not broken, f"docs point at symbols that no longer exist: {broken}"


def test_map_tier_docs_anchor_by_function_name_not_line_number():
    # Line-number anchors rot on every refactor; map-tier documents must anchor
    # by path or symbol name. Dated snapshots (docs/history/, review docs,
    # AUDIT_MATRIX evidence records) are exempt.
    offenders = {}
    for doc in (
        "README.md",
        "DOCS_MAP.md",
        "START_HERE.md",
        "AGENTS.md",
        "docs/architecture/SYSTEM_ZONES.md",
    ):
        hits = re.findall(r"\S+\.py:\d+", (ROOT / doc).read_text(encoding="utf-8"))
        if hits:
            offenders[doc] = hits[:5]
    assert not offenders, f"map-tier docs contain line-number anchors: {offenders}"
