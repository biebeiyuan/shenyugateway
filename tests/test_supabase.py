from __future__ import annotations

import asyncio
import ast
import importlib
import re
from pathlib import Path

from shenyu_gateway.supabase import SupabaseClient

from .fake_postgrest import apply_order, project_row, project_select, select_columns

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent


class _SuccessfulResponse:
    def raise_for_status(self):
        return None


def test_upsert_minimal_requests_no_row_representation():
    client = SupabaseClient("https://example.invalid", "test-key")
    captured = {}

    async def request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured.update(kwargs)
        return _SuccessfulResponse()

    client._request = request

    asyncio.run(client.upsert_minimal("example_table", [{"value": 1}], on_conflict="value"))

    assert captured["method"] == "POST"
    assert captured["params"] == {"on_conflict": "value"}
    assert captured["headers"]["Prefer"] == "resolution=merge-duplicates,return=minimal"


# ---------------------------------------------------------------------------
# The fake-select contract
# ---------------------------------------------------------------------------


def test_a_select_hides_every_column_it_did_not_ask_for():
    row = {"id": "1", "content": "note", "remind_on": "2026-09-01"}

    assert project_row(row, {"select": "id,content"}) == {"id": "1", "content": "note"}


def test_no_select_and_star_keep_every_column():
    row = {"id": "1", "content": "note"}

    assert project_row(row, None) == row
    assert project_row(row, {}) == row
    assert project_row(row, {"select": "*"}) == row
    assert project_row(row, {"select": "  "}) == row


def test_syntax_we_do_not_model_is_passed_through_untouched():
    # Better to hand back too much than to mis-project a string we cannot read:
    # a wrong projection would fail tests for a reason that is not the code's.
    row = {"id": "1", "content": "note"}

    for select in ("stars(id,chord)", "alias:content", "count::text", "notes!inner(id)"):
        assert select_columns({"select": select}) is None
        assert project_row(row, {"select": select}) == row


def test_a_selected_column_the_fixture_never_set_stays_absent():
    # A fake row is a fixture, not a table. Real PostgREST would return the
    # column as null, but inventing nulls here would assert something about the
    # database the fake cannot know. The guard runs the other way: an unselected
    # column must not be visible.
    rows = project_select([{"id": "1"}], {"select": "id,remind_on"})

    assert rows == [{"id": "1"}]


def _fake_query_methods(path: Path) -> list[ast.AsyncFunctionDef]:
    """Every `async def query` in a test module, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "query"
    ]


def _returns_a_row_set(method: ast.AsyncFunctionDef) -> bool:
    """Whether any return in this fake can hand back a non-empty row set.

    A fake that only ever returns `[]` or raises has no columns to hide, so it
    is not required to project.
    """
    for node in ast.walk(method):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        if isinstance(node.value, ast.List) and not node.value.elts:
            continue
        return True
    return False


def test_every_fake_that_returns_rows_honours_the_select_param():
    # A fake that ignores `select` hands back every column its fixture rows
    # carry, so removing a column from a real select string changes nothing any
    # test can see. Measured on 2026-08-28 before these fakes projected: 33 of
    # the 35 columns in _MEM_NOTE_SELECT_FIELDS_LIGHT could be deleted — `id`
    # and `content` included — with all 749 tests still green.
    offenders: dict[str, int] = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for method in _fake_query_methods(path):
            if not _returns_a_row_set(method):
                continue
            body = ast.get_source_segment(source, method) or ""
            if "project_select" in body or "project_row" in body or "super().query" in body:
                continue
            offenders[f"{path.name}::{method.lineno}"] = method.lineno
    assert not offenders, (
        "these Supabase fakes return rows without honouring params['select'] — "
        f"route them through tests/fake_postgrest.py: {sorted(offenders)}"
    )


def test_no_select_string_this_repository_sends_falls_into_the_unparseable_branch():
    # `_UNPARSEABLE` turns off projection for syntax the helper does not model —
    # the same silent return to the old permissive behaviour that this whole
    # projection effort exists to remove. It is a correct guard (mis-projecting
    # would be worse) but a dangerous one, because nothing else notices when a
    # select string starts landing in it. Measured 2026-08-29: every select
    # string in the package parses, none contain `(`, `:`, `!`, or `-`.
    fell_through: dict[str, str] = {}
    for path in sorted((ROOT / "shenyu_gateway").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"""["']select["']\s*:\s*(["'])(?P<value>[a-zA-Z0-9_,\s*]*?)\1""", text):
            value = match.group("value")
            if not value or value == "*":
                continue
            if select_columns({"select": value}) is None:
                line = text[: match.start()].count("\n") + 1
                fell_through[f"{path.name}:{line}"] = value
    # The named select constants are the ones that actually matter: the light
    # list feeds every automatic injection path.
    for module_name, attribute in (
        ("shenyu_gateway.mem_notes._helpers", "_MEM_NOTE_SELECT_FIELDS"),
        ("shenyu_gateway.mem_notes._helpers", "_MEM_NOTE_SELECT_FIELDS_LIGHT"),
        ("shenyu_gateway.stars._helpers", "STAR_SELECT"),
    ):
        value = getattr(importlib.import_module(module_name), attribute)
        if select_columns({"select": value}) is None:
            fell_through[f"{module_name}.{attribute}"] = value
    assert not fell_through, (
        "these select strings hit tests/fake_postgrest.py::_UNPARSEABLE, so the fakes "
        f"silently stop projecting them and drop back to returning every column: {fell_through}"
    )


# The fake-order contract
#
# Same shape of gap as `select`, found on 2026-08-30 while building 盼圃. The
# fake sorted with `str(row.get(field) or "")`, which cannot tell "no value"
# apart from "empty string", so rows with a NULL sort key came back *first*
# where the database puts them last. Nothing was red: the wall's dateless
# fruits were listed ahead of the ones actually coming due, and only reading
# the output by hand caught it.


def test_nulls_last_really_puts_nulls_last_in_both_directions():
    rows = [{"n": "b", "due": None}, {"n": "a", "due": "2026-09-01"}, {"n": "c", "due": "2026-09-20"}]

    ascending = apply_order(rows, {"order": "due.asc.nullslast"})
    assert [row["n"] for row in ascending] == ["a", "c", "b"]

    descending = apply_order(rows, {"order": "due.desc.nullslast"})
    assert [row["n"] for row in descending] == ["c", "a", "b"]

    # Without `nullslast` a missing value is just an empty string, which is what
    # PostgREST does too (nulls first on ascending by default).
    plain = apply_order(rows, {"order": "due.asc"})
    assert [row["n"] for row in plain] == ["b", "a", "c"]


def test_the_naive_sort_this_helper_replaces_would_fail_that():
    # The guard has to catch the bug that actually shipped, or it proves nothing.
    rows = [{"n": "b", "due": None}, {"n": "a", "due": "2026-09-01"}, {"n": "c", "due": "2026-09-20"}]
    naive = sorted(rows, key=lambda row: str(row.get("due") or ""))
    assert [row["n"] for row in naive] == ["b", "a", "c"]
    assert [row["n"] for row in naive] != [
        row["n"] for row in apply_order(rows, {"order": "due.asc.nullslast"})
    ]


def test_numbers_sort_as_numbers_not_as_text():
    # `version.desc` over 1/2/10 must give 10/2/1. Sorting those as strings
    # answers 2/10/1, which would let a fake hand back the wrong calendar page
    # revision without failing.
    rows = [{"version": 2}, {"version": 10}, {"version": 1}]
    assert [row["version"] for row in apply_order(rows, {"order": "version.desc"})] == [10, 2, 1]
    assert [row["version"] for row in apply_order(rows, {"order": "version.asc"})] == [1, 2, 10]


def test_several_order_keys_apply_left_to_right():
    rows = [
        {"n": "late", "due": "2026-09-01", "at": "2026-08-20"},
        {"n": "early", "due": "2026-09-01", "at": "2026-08-01"},
        {"n": "other", "due": "2026-08-01", "at": "2026-08-30"},
    ]
    ordered = apply_order(rows, {"order": "due.asc,at.asc"})
    assert [row["n"] for row in ordered] == ["other", "early", "late"]


def test_every_order_string_this_repository_sends_is_one_this_helper_models():
    # `order` is sent from dozens of places. A modifier the helper does not know
    # would be silently ignored, which is the same silent-pass failure the
    # `select` guards above exist to remove.
    known = {"asc", "desc", "nullsfirst", "nullslast"}
    unknown: dict[str, str] = {}
    for path in sorted((ROOT / "shenyu_gateway").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"""["']order["']\s*:\s*f?(["'])(?P<value>[^"']+)\1""", text):
            value = match.group("value")
            if "{" in value:  # an f-string built at runtime; not a literal to check
                continue
            for clause in value.split(","):
                bits = [bit.strip().lower() for bit in clause.strip().split(".")]
                for modifier in bits[1:]:
                    if modifier and modifier not in known:
                        line = text[: match.start()].count("\n") + 1
                        unknown[f"{path.name}:{line}"] = value
    assert not unknown, (
        "these order strings use modifiers tests/fake_postgrest.py::apply_order does not "
        f"model, so the fakes would sort them wrongly without failing: {unknown}"
    )


def test_no_fake_reimplements_order_sorting_by_hand():
    # One place decides what an order string means. Reading `order` to pass it
    # into `apply_order` is fine; sorting on it directly drifts from the helper,
    # and the drift is invisible until someone reads the output.
    hand_rolled: list[str] = []
    pattern = re.compile(
        r"""\.sort\(|sorted\(""",
    )
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        # This file is where the naive sort is *supposed* to appear: the guard
        # above proves the shipped bug by reproducing it. Exempting the whole
        # file is safe because it contains no Supabase fake of its own.
        if path.name == "test_supabase.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "fake_postgrest" not in text:
            continue
        for match in pattern.finditer(text):
            window = text[match.start() : match.start() + 240]
            if "order" in window or "reverse=" in window:
                line = text[: match.start()].count("\n") + 1
                hand_rolled.append(f"{path.name}:{line}")
    assert not hand_rolled, (
        f"order sorting belongs in tests/fake_postgrest.py::apply_order: {hand_rolled}"
    )


def test_no_fake_reimplements_select_parsing_by_hand():
    # One place decides what a select string means. A fake that skips `select`
    # in its own filter loop is fine (that is control-param handling), but a
    # fake that splits the string itself would drift from this helper.
    hand_rolled: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"""params\[["']select["']\]\.split|\.get\(["']select["']\)[^\n]*\.split""", text):
            hand_rolled.append(f"{path.name}:{text[: match.start()].count(chr(10)) + 1}")
    assert not hand_rolled, f"select parsing belongs in tests/fake_postgrest.py: {hand_rolled}"
