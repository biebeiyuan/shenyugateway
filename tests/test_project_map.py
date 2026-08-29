import re
import subprocess
from pathlib import Path

from shenyu_gateway import project_map


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


"""Modules allowed to define the +08:00 offset instead of importing it.

`runtime.py` is the home. `client_extra.py` is the documented exception: its
docstring forbids package-internal imports so importing it can never create a
cycle, which means it cannot reach runtime.
"""
_LOCAL_TZ_HOMES = {"runtime.py", "client_extra.py"}

# The two spellings of "+08:00 written in place". Both were in the tree until
# 2026-08-29; the rule that replaced them lives in AGENTS.md § New subsystem
# growth path, and a documented rule alone is what this test exists to distrust.
_LOCAL_TZ_LITERALS = (
    re.compile(r"timezone\(\s*timedelta\(\s*hours\s*=\s*8\s*\)\s*\)"),
    re.compile(r"""ZoneInfo\(\s*["']Asia/Shanghai["']\s*\)"""),
)


def test_the_local_timezone_is_defined_in_exactly_one_place():
    # Nine modules each spelled this out before it was consolidated, so any
    # change to "which day is it" depended on someone recalling all nine. That
    # is a documented convention now, and this repository measured on the same
    # night that documented conventions fail silently — hence a test, matching
    # the line-ending and --abandoned guards rather than trusting the doc.
    offenders: dict[str, list[str]] = {}
    for path in sorted((ROOT / "shenyu_gateway").rglob("*.py")):
        if path.name in _LOCAL_TZ_HOMES:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _LOCAL_TZ_LITERALS:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.setdefault(path.relative_to(ROOT).as_posix(), []).append(
                    f"line {line}: {match.group(0)}"
                )
    assert not offenders, (
        "the local timezone has one home — import LOCAL_DAY_TZ from "
        f"shenyu_gateway/runtime.py instead of writing the offset in place: {offenders}"
    )


def test_the_timezone_home_and_its_one_exception_still_exist():
    # The exemption list above is only honest if both files still hold what it
    # claims: a bare name in a skip set silently stops guarding anything.
    runtime = (ROOT / "shenyu_gateway" / "runtime.py").read_text(encoding="utf-8")
    assert re.search(r"^LOCAL_DAY_TZ\s*=", runtime, flags=re.MULTILINE)
    extra = (ROOT / "shenyu_gateway" / "client_extra.py").read_text(encoding="utf-8")
    assert "free of package-internal imports" in extra, (
        "client_extra.py is exempt only because it may not import from the package; "
        "if that contract is gone, it should import LOCAL_DAY_TZ like everyone else"
    )


_MAP_TABLES = (
    ("docs/architecture/SYSTEM_ZONES.md", "## 跨区关键桥梁"),
    ("README.md", "### 按产品对象反查"),
    ("DOCS_MAP.md", "## 现行文档"),
)


def test_every_row_of_the_three_map_tables_parses():
    # A row whose cell count disagrees with the header cannot be zipped into a
    # record, so the parser skips it — the table still looks whole and the row is
    # simply gone from 家里地图. Measured when this guard was written: all 33 rows
    # across the three tables parse, so the check is silent until someone's hand
    # edit drops or adds a `|`.
    warnings: list[str] = []
    for doc, heading in _MAP_TABLES:
        text = (ROOT / doc).read_text(encoding="utf-8")
        rows = project_map._table_after_heading(text, heading, warnings, source=doc)
        assert rows, f"{doc} {heading} parsed to nothing"
    assert not warnings, f"map table rows the project map silently drops: {warnings}"


def test_a_malformed_table_row_is_reported_not_dropped_in_silence():
    # The measurement above only stays meaningful if a bad row is actually loud;
    # otherwise a future refactor could restore the silent skip and the clean
    # measurement would keep passing.
    table = "\n".join(
        (
            "## 现行文档",
            "",
            "| 文档 | 作用 | 何时读 |",
            "| --- | --- | --- |",
            "| A.md | 甲 | 开工前 |",
            "| B.md | 乙 |",
            "| C.md | 丙 | 收工后 |",
        )
    )
    warnings: list[str] = []
    rows = project_map._table_after_heading(table, "## 现行文档", warnings, source="测试表")
    assert [row["文档"] for row in rows] == ["A.md", "C.md"]
    assert len(warnings) == 1
    assert "B.md" in warnings[0] and "测试表" in warnings[0]


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
