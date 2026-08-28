from __future__ import annotations

import asyncio
import ast
import re
from pathlib import Path

from shenyu_gateway.supabase import SupabaseClient

from .fake_postgrest import project_row, project_select, select_columns

TESTS_DIR = Path(__file__).resolve().parent


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
