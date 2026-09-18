from __future__ import annotations

"""VPS-local original-text archive, independent of gateway runtime retention.

This is NOT a context/history provider. Readers expose the existing archive API
shape; original rows and tombstones survive session cleanup. Legacy handoff copies
are folded only in the reading view, never deleted or rewritten during import.
"""

import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .runtime import LOCAL_DAY_TZ

_COLUMNS = ('id', 'session_tag', 'thread', 'client_name', 'role', 'content',
            'content_hash', 'event_at', 'archived_at', 'deleted_at')
_ORIGINAL = _COLUMNS[:-1]
_PUBLIC = ('id', 'session_tag', 'role', 'content', 'event_at', 'archived_at')
_APPLICATION_ID = 0x53484341  # SHCA; refuse an unrelated or runtime database.
_VERSION = 1
# Capability floor: FILTER aggregates require 3.30; Python itself requires 3.12.
_MIN_SQLITE = (3, 30, 0)
# Unlike ROW_NUMBER(), this selection can be flattened so the caller's day/time
# index and LIMIT apply before examining unrelated history. The earlier-row test
# must remain global: moving a page cursor inside it could resurrect old copies.
_VISIBLE_ROWS = """SELECT current.* FROM archive_messages AS current
    WHERE current.deleted_at IS NULL AND NOT EXISTS (
        SELECT 1 FROM archive_messages AS earlier
        WHERE earlier.fold_key = current.fold_key AND earlier.deleted_at IS NULL
          AND (earlier.event_us, earlier.archive_us, earlier.id)
              < (current.event_us, current.archive_us, current.id)
    )"""
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _instant(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('archive timestamp is required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid archive timestamp') from exc
    # Legacy archive cursor handling has always treated a naive time as UTC.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _micros(value: str) -> int:
    delta = _instant(value).astimezone(timezone.utc) - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _day(value: str) -> str:
    return _instant(value).astimezone(LOCAL_DAY_TZ).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _limit(value: int, default: int, *, maximum: int = 1000) -> int:
    return max(1, min(int(value or default), maximum))


def _uncased_literal_fragment(needle: str) -> str:
    """A necessary literal substring safe for SQLite's C-level instr prefilter.

    SQLite LIKE is ASCII-case-insensitive, not Python's Unicode IGNORECASE:
    blind LIKE prefiltering would lose É/é, k/K, i/ı and s/ſ matches. An uncased
    run (e.g. Chinese, digits or punctuation) has no such ambiguity. Pure cased
    words use the regex alone. instr also preserves %, _, quotes and NUL bytes.
    """
    longest = current = ''
    for char in needle:
        if char.lower() == char.upper() == char.casefold():
            current += char
            if len(current) > len(longest):
                longest = current
        else:
            current = ''
    return longest


class LocalChatArchive:
    """One private SQLite file. Creation must be an explicit migration action."""

    def __init__(self, path: str | Path, *, create: bool = False):
        if sqlite3.sqlite_version_info < _MIN_SQLITE:
            raise RuntimeError('local chat archive requires SQLite >= 3.30.0; '
                               f'found {sqlite3.sqlite_version_info}')
        self.path = Path(path).expanduser().resolve()
        created = False
        if not self.path.exists():
            if not create:
                raise FileNotFoundError('local archive is not initialized; import it before cutover')
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Exclusive creation avoids altering permissions/content of another file.
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            created = True
        try:
            uri = self.path.as_uri() + ('?mode=rw' if created else '?mode=ro')
            with closing(sqlite3.connect(uri, uri=True)) as conn, conn:
                app_id = conn.execute('PRAGMA application_id').fetchone()[0]
                version = conn.execute('PRAGMA user_version').fetchone()[0]
                if not created:
                    if app_id != _APPLICATION_ID or version != _VERSION:
                        raise ValueError('not a supported Shenyu chat archive database')
                    conn.execute(f'SELECT {",".join(_COLUMNS)} FROM archive_messages LIMIT 0')
                    return
                conn.execute('PRAGMA journal_mode = WAL')
                conn.execute('PRAGMA synchronous = FULL')
                conn.executescript('''
                    CREATE TABLE archive_messages (
                        id TEXT PRIMARY KEY,
                        session_tag TEXT, thread TEXT, client_name TEXT,
                        role TEXT NOT NULL CHECK (role IN ('user','assistant')),
                        content TEXT NOT NULL, content_hash TEXT,
                        event_at TEXT, archived_at TEXT NOT NULL, deleted_at TEXT,
                        event_us INTEGER NOT NULL, archive_us INTEGER NOT NULL,
                        event_day TEXT NOT NULL, fold_key TEXT NOT NULL
                    );
                    CREATE INDEX archive_time ON archive_messages(event_us, archive_us, id);
                    CREATE INDEX archive_day ON archive_messages(event_day, event_us, archive_us, id);
                    CREATE INDEX archive_session ON archive_messages(session_tag, event_us, archive_us, id);
                    CREATE INDEX archive_fold ON archive_messages(fold_key, event_us, archive_us, id);
                ''')
                conn.execute(f'CREATE VIEW archive_visible AS {_VISIBLE_ROWS}')
                conn.execute(f'PRAGMA application_id = {_APPLICATION_ID}')
                conn.execute(f'PRAGMA user_version = {_VERSION}')
        except Exception:
            if created:
                self.path.unlink(missing_ok=True)
                Path(str(self.path) + '-wal').unlink(missing_ok=True)
                Path(str(self.path) + '-shm').unlink(missing_ok=True)
            raise

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        uri = self.path.as_uri() + ('?mode=rw' if write else '?mode=ro')
        # Writes below issue BEGIN IMMEDIATE explicitly; with conn commits or
        # rolls back that transaction. Do not also ask CPython to BEGIN implicitly.
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA busy_timeout = 5000')
            if write:
                conn.execute('PRAGMA synchronous = FULL')
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _validated(row: dict, *, legacy: bool) -> dict:
        if not isinstance(row, dict) or set(row) - set(_COLUMNS):
            raise ValueError('unsupported archive row fields')
        result = {key: row.get(key) for key in _COLUMNS}
        ident = result['id']
        if not isinstance(ident, str) or not ident or '|' in ident or '\x00' in ident:
            raise ValueError('archive id is required and must be cursor-safe')
        if result['role'] not in ('user', 'assistant') or not isinstance(result['content'], str):
            raise ValueError('only user/assistant original text belongs in the archive')
        for key in ('session_tag', 'thread', 'client_name', 'content_hash'):
            if result[key] is not None and not isinstance(result[key], str):
                raise ValueError(f'invalid archive {key}')
        event = result['event_at'] or result['archived_at']
        result['event_us'] = _micros(event)
        result['archive_us'] = _micros(result['archived_at'])
        result['event_day'] = _day(event)
        if result['deleted_at'] is not None:
            _micros(result['deleted_at'])
        digest = result['content_hash']
        result['fold_key'] = (f'legacy:{result["event_day"]}\x00{digest}'
                              if legacy and digest else f'id:{ident}')
        return result

    def _write(self, rows: Iterable[dict], *, legacy: bool, capture: bool = False) -> int:
        records = [self._validated(row, legacy=legacy) for row in rows]
        inserted = 0
        with self._connect(write=True) as conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in records:
                existing = conn.execute('SELECT * FROM archive_messages WHERE id=?', (row['id'],)).fetchone()
                if existing:
                    if (row.get("content_hash") == "event:v1:" + row["id"]
                            and existing["content_hash"] == row["content_hash"]
                            and existing["role"] == row["role"] and capture):
                        # Capture event identity is immutable even when a client's
                        # projection changes. Never overwrite or revive this row.
                        continue
                    if any(existing[key] != row[key] for key in _ORIGINAL):
                        # Do not print resident content as failure evidence.
                        raise ValueError(f'archive original conflict for id {row["id"]}')
                    # Re-import may add a source tombstone, never revive a local deletion.
                    if existing['deleted_at'] is None and row['deleted_at'] is not None:
                        conn.execute('UPDATE archive_messages SET deleted_at=? WHERE id=?',
                                     (row['deleted_at'], row['id']))
                    continue
                columns = tuple(row)
                conn.execute(f'INSERT INTO archive_messages ({",".join(columns)}) '
                             f'VALUES ({",".join("?" for _ in columns)})',
                             tuple(row[key] for key in columns))
                inserted += 1
        return inserted

    def import_rows(self, rows: Iterable[dict]) -> int:
        """Preserve source IDs/bytes; legacy folding is a read-only presentation rule."""
        return self._write(rows, legacy=True)

    def append_rows(self, rows: Iterable[dict]) -> int:
        """ID-based writes: distinct IDs remain distinct even for identical text."""
        return self._write(rows, legacy=False)

    def append_legacy_rows(self, rows: Iterable[dict]) -> int:
        """Window capture: immutable identified events plus legacy hash-based rows."""
        return self._write(({**row, 'id': row.get('id') or str(uuid.uuid4()),
                             'deleted_at': row.get('deleted_at')} for row in rows),
                           legacy=True, capture=True)

    def export_rows(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                f'SELECT {",".join(_COLUMNS)} FROM archive_messages ORDER BY id')]

    def verify_rows(self, rows: Iterable[dict]) -> dict[str, int]:
        """Exact cutover/snapshot proof, not a health check after further writes.

        Compare only against an export of the SAME frozen snapshot. Additional
        messages or local tombstones correctly fail; never repair in place.
        """
        source: dict[str, dict] = {}
        for row in rows:
            self._validated(row, legacy=True)
            if row['id'] in source:
                raise ValueError('duplicate source id in verification input')
            source[row['id']] = {key: row.get(key) for key in _COLUMNS}
        actual = {row['id']: row for row in self.export_rows()}
        if source.keys() != actual.keys():
            raise ValueError('archive verification failed: source/local ID sets differ')
        if any(source[key] != actual[key] for key in source):
            raise ValueError('archive verification failed: original fields or tombstones differ')
        return self.stats()

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            total, active = conn.execute('SELECT COUNT(*), COUNT(*) FILTER '
                                          '(WHERE deleted_at IS NULL) FROM archive_messages').fetchone()
            visible = conn.execute('SELECT COUNT(DISTINCT fold_key) FROM archive_messages '
                                   'WHERE deleted_at IS NULL').fetchone()[0]
        return {'total': total, 'active': active, 'visible': visible}

    @staticmethod
    def cursor(row: dict) -> str:
        return f'{row["event_at"] or row["archived_at"]}|{row["archived_at"]}|{row["id"]}'

    @staticmethod
    def _cursor_filter(raw: str, op: str) -> tuple[str, tuple]:
        parts = raw.split('|')
        if len(parts) == 3 and all(parts):
            return f'(event_us, archive_us, id) {op} (?,?,?)', (_micros(parts[0]), _micros(parts[1]), parts[2])
        if len(parts) == 2 and all(parts):
            return f'(event_us, id) {op} (?,?)', (_micros(parts[0]), parts[1])
        if len(parts) == 1:
            return f'event_us {op} ?', (_micros(raw),)
        raise ValueError('invalid archive cursor')

    def days(self, month: str | None = None) -> list[dict]:
        params: tuple = ()
        clause = ''
        if month:
            if not re.fullmatch(r'\d{4}-\d{2}', month):
                raise ValueError('month must be YYYY-MM')
            first = date.fromisoformat(month + '-01')
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            clause = 'WHERE event_day >= ? AND event_day < ?'
            params = (first.isoformat(), last.isoformat())
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                f'SELECT event_day AS date, COUNT(*) AS count FROM ({_VISIBLE_ROWS}) '
                f'{clause} GROUP BY event_day ORDER BY event_day', params)]

    def list_messages(self, *, date: str | None = None, before: str | None = None,
                      after: str | None = None, limit: int = 200, around_days: int = 0) -> list[dict]:
        from datetime import date as date_type
        params: tuple = ()
        where = ''
        ascending = bool(date or after)
        if date:
            anchor = date_type.fromisoformat(date)
            span = max(0, min(int(around_days or 0), 7))
            where = 'WHERE event_day >= ? AND event_day < ?'
            params = ((anchor - timedelta(days=span)).isoformat(),
                      (anchor + timedelta(days=span + 1)).isoformat())
        elif before or after:
            clause, params = self._cursor_filter(after or before, '>' if after else '<')
            where = 'WHERE ' + clause
        order = 'ASC' if ascending else 'DESC'
        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(
                f'SELECT {",".join(_PUBLIC)} FROM ({_VISIBLE_ROWS}) {where} '
                f'ORDER BY event_us {order}, archive_us {order}, id {order} LIMIT ?',
                (*params, _limit(limit, 200)))]
        return rows if ascending else rows[::-1]

    def search(self, query: str, *, role: str | None = None, limit: int = 60,
               cursor: str | None = None) -> dict:
        needle = (query or '').strip()
        empty = {'results': [], 'count': 0, 'has_more': False, 'query': needle, 'next_cursor': None}
        if not needle:
            return empty
        # Exact old Python authority: literal regex + IGNORECASE. Unlike LIKE/FTS
        # this preserves %, _, quotes, one/two-character Chinese and emoji queries.
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        clauses = []
        params: list[Any] = []
        fragment = _uncased_literal_fragment(needle)
        if fragment:
            clauses.append('instr(content, ?) > 0')
            params.append(fragment)
        # Keep regex as the authority; the prefilter may admit false positives,
        # never remove a true match. Put the cheap filter before the callback.
        clauses.append('archive_literal(content) = 1')
        if role in ('user', 'assistant'):
            clauses.append('role = ?'); params.append(role)
        if cursor:
            clause, values = self._cursor_filter(cursor, '<')
            clauses.append(clause); params.extend(values)
        # Match the cloud search endpoint, including limit=0 -> 1.
        cap = _limit(limit, 1, maximum=200)
        with self._connect() as conn:
            conn.create_function('archive_literal', 1, lambda text: int(bool(pattern.search(text or ''))), deterministic=True)
            rows = [dict(row) for row in conn.execute(
                f'SELECT {",".join(_PUBLIC)} FROM ({_VISIBLE_ROWS}) WHERE {" AND ".join(clauses)} '
                'ORDER BY event_us DESC, archive_us DESC, id DESC LIMIT ?', (*params, cap + 1))]
        has_more = len(rows) > cap
        hits = rows[:cap]
        results = []
        for row in hits:
            text = row.pop('content')
            match = pattern.search(text)
            if match is None:
                # An invariant violation must fail equally under python -O;
                # silently skipping a hit would corrupt counts/cursor semantics.
                raise RuntimeError('archive search predicate mismatch')
            results.append({**row,
                'snippet_before': text[max(0, match.start()-30):match.start()],
                'snippet_match': text[match.start():match.end()],
                'snippet_after': text[match.end():match.end()+30]})
        return {'results': results, 'count': len(results), 'has_more': has_more,
                'query': needle, 'next_cursor': self.cursor(hits[-1]) if has_more else None}

    def recall_candidates(self, terms: list[str], *, limit: int = 200) -> list[dict]:
        """Full originals for chat Recall; same visibility/literal rules as search.

        Keep Recall's bounded newest-candidate pool and OR term retrieval. Scoring
        belongs to the tool service, not storage. Filter before LIMIT, and fold
        globally before either, so hidden handoff copies cannot consume the pool.
        """
        needles = list(dict.fromkeys(term for term in terms if term))
        clauses: list[str] = []
        params: list[Any] = []
        pattern = None
        if needles:
            pattern = re.compile('|'.join(re.escape(term) for term in needles), re.IGNORECASE)
            fragments = [_uncased_literal_fragment(term) for term in needles]
            if all(fragments):
                clauses.append('(' + ' OR '.join('instr(content, ?) > 0' for _ in fragments) + ')')
                params.extend(fragments)
            clauses.append('archive_literal(content) = 1')
        where = 'WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self._connect() as conn:
            if pattern is not None:
                conn.create_function('archive_literal', 1,
                                     lambda text: int(bool(pattern.search(text or ''))), deterministic=True)
            return [dict(row) for row in conn.execute(
                f'SELECT {",".join(_PUBLIC)} FROM ({_VISIBLE_ROWS}) {where} '
                'ORDER BY event_us DESC, archive_us DESC, id DESC LIMIT ?',
                (*params, _limit(limit, 200, maximum=200)))]

    def read_message(self, message_id: str) -> dict | None:
        """Read a currently visible original by ID, never a tombstone/folded copy."""
        with self._connect() as conn:
            row = conn.execute(f'SELECT {",".join(_PUBLIC)} FROM ({_VISIBLE_ROWS}) '
                               'WHERE id = ?', (message_id,)).fetchone()
        return dict(row) if row else None

    def soft_delete(self, message_id: str) -> int:
        with self._connect(write=True) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT fold_key FROM archive_messages WHERE id=?', (message_id,)).fetchone()
            if not row:
                return 0
            result = conn.execute('UPDATE archive_messages SET deleted_at=? '
                                  'WHERE fold_key=? AND deleted_at IS NULL', (_now(), row['fold_key']))
            return result.rowcount

    def backup(self, destination: str | Path) -> Path:
        target = Path(destination).expanduser().absolute()
        if target.resolve() == self.path:
            raise ValueError('backup destination must differ from the source')
        if target.exists() or target.is_symlink():
            raise FileExistsError('backup destination already exists')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='.archive-backup-', dir=target.parent)
        os.close(fd)
        try:
            with self._connect() as source:
                output = sqlite3.connect(temporary)
                try:
                    source.backup(output, pages=256)
                    # This is the finished private snapshot, never the live DB.
                    # Remove the snapshot's WAL requirement so a single-file
                    # backup also opens on read-only media without -wal/-shm.
                    output.execute('PRAGMA journal_mode = DELETE')
                    if output.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('backup integrity check failed')
                finally:
                    output.close()
            with open(temporary, 'rb') as completed:
                os.fsync(completed.fileno())
            # No-clobber publication; even a concurrent writer cannot be overwritten.
            os.link(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return target


def local_archive_for_config(cfg: Any) -> LocalChatArchive | None:
    """Deployment switch only; never create a blank production archive on demand."""
    if getattr(cfg, 'chat_archive_backend', 'supabase') != 'sqlite':
        return None
    runtime = Path(cfg.gateway_db_path).expanduser().resolve()
    configured = getattr(cfg, 'chat_archive_db_path', '')
    path = Path(configured).expanduser().resolve() if configured else runtime.with_name('shenyu_chat_archive.db')
    if path == runtime:
        raise ValueError('chat archive must be separate from the runtime database')
    return LocalChatArchive(path)
