"""Shared PostgREST behaviour for the test fakes that stand in for Supabase.

A fake that ignores `params["select"]` hands back every column its fixture rows
happen to carry, so dropping a column from a real `select` string changes
nothing a test can see. That one gap hides a whole class of silent failure:
`_MEM_NOTE_SELECT_FIELDS_LIGHT` lost `remind_on`/`reminded_at` and 749 tests
stayed green. Measured on 2026-08-28: 33 of the 35 columns in that list could be
deleted without a single behavioural test noticing.

Fakes that answer a real `select` should route their rows through
`project_select` on the way out.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# PostgREST select syntax we do not model: embedded resources `table(cols)`,
# aliases `alias:column`, casts `column::text`, and inverted embeds. This
# repository sends none of them, so rather than mis-project a string we do not
# understand, we hand the rows back untouched.
_UNPARSEABLE = ("(", ":", "!", "-")


def select_columns(params: Mapping[str, Any] | None) -> list[str] | None:
    """Columns a `select` param asks for, or None when every column is fine.

    None means "do not project": either no `select` was sent, it was `*`, or it
    uses syntax this helper deliberately does not model.
    """
    raw = (params or {}).get("select")
    if not isinstance(raw, str):
        return None
    select = raw.strip()
    if not select or select == "*":
        return None
    if any(token in select for token in _UNPARSEABLE):
        return None
    columns = [part.strip() for part in select.split(",")]
    return [column for column in columns if column] or None


def project_row(row: Mapping[str, Any], params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop the columns a `select` param did not ask for.

    Columns the fixture row never defined stay absent rather than appearing as
    None. Real PostgREST would return them as null, but a fake row is a fixture,
    not a table — inventing nulls for columns its author never set would assert
    something about the database the fake cannot know. The guard we want runs in
    the other direction: a column that was not selected must not be visible.
    """
    columns = select_columns(params)
    if columns is None:
        return dict(row)
    return {column: row[column] for column in columns if column in row}


def project_select(
    rows: Iterable[Mapping[str, Any]], params: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """`project_row` over a result set."""
    columns = select_columns(params)
    if columns is None:
        return [dict(row) for row in rows]
    return [{column: row[column] for column in columns if column in row} for row in rows]
