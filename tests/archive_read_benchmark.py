"""Reproduce the archive read-cost review using disposable synthetic rows only.

Run: python -m tests.archive_read_benchmark --rows 20861 100000
No credentials, network, production paths, or real conversation contents.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sqlite3
import statistics
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shenyu_gateway.local_chat_archive import LocalChatArchive

LEGACY = '''SELECT * FROM (SELECT *, ROW_NUMBER() OVER (
    PARTITION BY fold_key ORDER BY event_us,archive_us,id) AS copy_rank
    FROM archive_messages WHERE deleted_at IS NULL) WHERE copy_rank=1'''
PUBLIC = 'id,session_tag,role,content,event_at,archived_at'


def seed(store, count):
    origin = datetime(2025, 10, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(count):
        k = i - 1 if i % 10 == 9 else i  # 10% legacy handoff copies
        stamp = (origin + timedelta(seconds=k * 365 * 86400 // count)).isoformat()
        rows.append(dict(id=f'{i:09}', session_tag='A' if k % 2 else 'B', thread='main',
                         client_name='synthetic', role='user',
                         content=('沈予' if k % 503 == 0 else '普通') + '合成对话内容仅用于性能测量。' * 18,
                         content_hash=f'h{k}', event_at=stamp, archived_at=stamp, deleted_at=None))
    store.import_rows(rows)


def current_query(store, method, **kwargs):
    """Capture the real public method's SQL, rather than handwrite its replacement."""
    queries = []
    original = store._connect
    @contextmanager
    def traced(**options):
        with original(**options) as conn:
            conn.set_trace_callback(queries.append)
            yield conn
    store._connect = traced
    try:
        getattr(store, method)(**kwargs)
    finally:
        store._connect = original
    return next(q for q in reversed(queries) if q.lstrip().upper().startswith('SELECT'))


def measure(conn, query, repeats=3):
    calls = [0]
    steps = [0]
    pattern = re.compile('沈予', re.IGNORECASE)
    def matches(text):
        calls[0] += 1
        return int(bool(pattern.search(text or '')))
    def progress():
        steps[0] += 100
        return 0
    conn.create_function('archive_literal', 1, matches, deterministic=True)
    plan = [r[3] for r in conn.execute('EXPLAIN QUERY PLAN ' + query)]
    timings = []
    conn.set_progress_handler(progress, 100)
    try:
        for _ in range(repeats):
            calls[0] = steps[0] = 0
            start = time.perf_counter()
            rows = conn.execute(query).fetchall()
            timings.append((time.perf_counter() - start) * 1000)
    finally:
        conn.set_progress_handler(None, 0)
    return ({'median_ms': round(statistics.median(timings), 3), 'rows_returned': len(rows),
             'vm_steps_approx': steps[0], 'python_callbacks': calls[0], 'plan': plan}, rows)


def benchmark(count):
    with tempfile.TemporaryDirectory(prefix='shenyu-synthetic-bench-') as directory:
        store = LocalChatArchive(Path(directory) / 'archive.db', create=True)
        seed(store, count)
        old_queries = {
            'days': f"SELECT event_day AS date,COUNT(*) AS count FROM ({LEGACY}) WHERE event_day>='2026-09-01' AND event_day<'2026-10-01' GROUP BY event_day ORDER BY event_day",
            'recent': f'SELECT {PUBLIC} FROM ({LEGACY}) ORDER BY event_us DESC,archive_us DESC,id DESC LIMIT 60',
            'search': f'SELECT {PUBLIC} FROM ({LEGACY}) WHERE archive_literal(content)=1 ORDER BY event_us DESC,archive_us DESC,id DESC LIMIT 61',
        }
        new_queries = {
            'days': current_query(store, 'days', month='2026-09'),
            'recent': current_query(store, 'list_messages', limit=60),
            'search': current_query(store, 'search', query='沈予'),
        }
        result = {}
        with store._connect() as conn:
            for name in old_queries:
                before, old_rows = measure(conn, old_queries[name])
                after, new_rows = measure(conn, new_queries[name])
                assert [tuple(r) for r in old_rows] == [tuple(r) for r in new_rows], name
                result[name] = {'before': before, 'after': after, 'equal_results': True}
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, nargs='+', default=[20861, 100000])
    args = parser.parse_args()
    if any(n < 1 or n > 500000 for n in args.rows):
        parser.error('rows must be between 1 and 500000 (disposable synthetic data only)')
    results = {str(count): benchmark(count) for count in args.rows}
    print(json.dumps({'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                      'kind': 'synthetic, not VPS/production', 'results': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
