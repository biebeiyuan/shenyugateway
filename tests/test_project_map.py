import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _maintenance_map() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    return readme.split("## Maintenance Map", 1)[1].split("## Subsystem Guides", 1)[0]


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
        if path.suffix in {".ts", ".vue"}
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
    }


def test_readme_maintenance_map_covers_runtime_entry_files():
    missing = sorted(_expected_map_paths() - _indexed_map_paths())
    assert not missing, f"README Maintenance Map is missing: {missing}"


def test_readme_maintenance_map_has_no_stale_runtime_entry_files():
    stale = sorted(path for path in _indexed_map_paths() if not (ROOT / path).is_file())
    assert not stale, f"README Maintenance Map has stale paths: {stale}"
