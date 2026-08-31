"""Shared PostgREST behaviour for the test fakes that stand in for Supabase.

A fake that ignores `params["select"]` hands back every column its fixture rows
happen to carry, so dropping a column from a real `select` string changes
nothing a test can see. That one gap hides a whole class of silent failure:
`_MEM_NOTE_SELECT_FIELDS_LIGHT` lost `remind_on`/`reminded_at` and 749 tests
stayed green. Measured on 2026-08-28: 33 of the 35 columns in that list could be
deleted without a single behavioural test noticing.

`params["order"]` has the same shape of gap, found on 2026-08-30 while building
盼圃: a fake that sorts by `str(row.get(field) or "")` treats NULL as the empty
string and puts null-valued rows *first*, where real PostgREST `nullslast` puts
them last. That fake had the wall's dateless fruits — the ones the whole feature
exists for — sorted ahead of the ones actually coming due, with every test green.
`order` is sent from 53 places in the gateway, so route sorting through
`apply_order` rather than re-deriving it per fake.

Fakes that answer a real `select` should route their rows through
`project_select` on the way out, and fakes that honour `order` should use
`apply_order`.
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


def apply_order(
    rows: Iterable[Mapping[str, Any]], params: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Sort rows the way PostgREST's `order` param says to.

    Multiple keys are applied right-to-left through a stable sort, which gives
    the same result as one comparison over the whole tuple.

    `nullslast` is the reason this helper exists. A fake that keys on
    `str(value or "")` cannot distinguish "no value" from "empty string", so
    null-valued rows sort first — the opposite of what the database does.

    Numbers compare as numbers, not as text: `version.desc` over 1/2/10 must
    give 10/2/1, and string ordering would answer 2/10/1. Everything else
    compares as a string, which is correct for the ISO dates and timestamps
    this repository orders by.
    """
    ordered = [dict(row) for row in rows]
    clauses = str((params or {}).get("order") or "")
    if not clauses:
        return ordered
    for clause in reversed([part.strip() for part in clauses.split(",") if part.strip()]):
        bits = clause.split(".")
        field = bits[0]
        modifiers = {bit.lower() for bit in bits[1:]}
        descending = "desc" in modifiers
        nulls_last = "nullslast" in modifiers

        numeric = all(
            isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)
            for row in ordered
            if row.get(field) is not None
        )

        def key(row: Mapping[str, Any], field: str = field, nulls_last: bool = nulls_last,
                descending: bool = descending, numeric: bool = numeric) -> tuple[bool, Any]:
            value = row.get(field)
            if numeric:
                sortable: Any = value if isinstance(value, (int, float)) else 0
            else:
                sortable = str(value if value is not None else "")
            if not nulls_last:
                return (False, sortable)
            missing = value is None or value == ""
            # `reverse=True` flips this flag along with the value, so pre-invert
            # it to keep nulls last in both directions.
            return ((not missing) if descending else missing, sortable)

        ordered.sort(key=key, reverse=descending)
    return ordered
