from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "shenyu_gateway.db"


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def count_prunable(conn: sqlite3.Connection, table: str, keep: int) -> int:
    if not table_exists(conn, table):
        return 0
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM {table}
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY session_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM {table}
            )
            WHERE rn > ?
        )
        """,
        (keep,),
    ).fetchone()
    return int(row["count"] or 0)


def prune_table(conn: sqlite3.Connection, table: str, keep: int) -> int:
    if not table_exists(conn, table):
        return 0
    cursor = conn.execute(
        f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY session_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM {table}
            )
            WHERE rn > ?
        )
        """,
        (keep,),
    )
    return int(cursor.rowcount or 0)


def refresh_session_counts(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "gateway_sessions") or not table_exists(conn, "gateway_messages"):
        return
    conn.execute(
        """
        UPDATE gateway_sessions
        SET message_count = (
            SELECT COUNT(*)
            FROM gateway_messages
            WHERE gateway_messages.session_id = gateway_sessions.id
        )
        """
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Keep only the newest SQLite gateway history rows per session."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to shenyu_gateway.db")
    parser.add_argument("--keep", type=int, default=15, help="Rows to keep per session")
    parser.add_argument("--apply", action="store_true", help="Actually delete rows")
    parser.add_argument("--vacuum", action="store_true", help="Run VACUUM after deleting")
    args = parser.parse_args()

    keep = max(1, args.keep)
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        targets = ("gateway_messages", "request_context_snapshots")
        planned = {table: count_prunable(conn, table, keep) for table in targets}
        print(f"Database: {db_path}")
        print(f"Keep newest rows per session: {keep}")
        for table, count in planned.items():
            print(f"{table}: {count} row(s) would be removed")

        if not args.apply:
            print("Dry run only. Add --apply to delete these rows.")
            return 0

        deleted = {table: prune_table(conn, table, keep) for table in targets}
        refresh_session_counts(conn)
        conn.commit()
        for table, count in deleted.items():
            print(f"{table}: removed {count} row(s)")
    finally:
        conn.close()

    if args.apply and args.vacuum:
        vacuum_conn = sqlite3.connect(db_path)
        try:
            vacuum_conn.execute("VACUUM")
            print("VACUUM complete")
        finally:
            vacuum_conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
