"""Review regressions: storage safety/cost, never a model-history rewrite."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from shenyu_gateway import local_chat_archive as archive_module
from shenyu_gateway.chat_archive import ChatArchiveService
from shenyu_gateway.local_chat_archive import LocalChatArchive
from shenyu_gateway.schemas import ConfigUpdate
from shenyu_gateway.store import GatewayStore
from .test_local_chat_archive import row

ROOT = Path(__file__).resolve().parents[1]


def measured_call(store, method, **kwargs):
    steps = [0]
    original = store._connect
    @contextmanager
    def counted(**options):
        with original(**options) as conn:
            def tick():
                steps[0] += 100
                return 0
            conn.set_progress_handler(tick, 100)
            yield conn
    store._connect = counted
    try:
        result = getattr(store, method)(**kwargs)
    finally:
        store._connect = original
    return result, steps[0]


@pytest.mark.parametrize('method,kwargs', [
    ('list_messages', {'limit': 60}),
    ('days', {'month': '2026-09'}),
])
def test_recent_and_month_reads_do_not_rank_entire_archive(tmp_path, method, kwargs):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row(f'old-{i:05}', event='2026-01-01T00:00:00Z') for i in range(4000)]
                      + [row('recent-a'), row('recent-b')])
    result, instructions = measured_call(store, method, **kwargs)
    assert result
    # Broad instruction budget, not wall-clock timing or brittle plan text.
    # A 4000-row ROW_NUMBER view takes >300k instructions; indexed reads <10k.
    assert instructions < 20000, f'{method} scanned/ranked history: ~{instructions} VM steps'


def test_old_v1_window_view_does_not_force_full_scan_or_require_migration(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row(f'old-{i:05}', event='2026-01-01T00:00:00Z') for i in range(4000)]
                      + [row('recent')])
    with sqlite3.connect(store.path) as conn:
        conn.executescript('''DROP VIEW archive_visible;
        CREATE VIEW archive_visible AS SELECT * FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY fold_key ORDER BY event_us, archive_us, id) AS copy_rank
          FROM archive_messages WHERE deleted_at IS NULL) WHERE copy_rank = 1;''')
    reopened = LocalChatArchive(store.path)
    result, instructions = measured_call(reopened, 'days', month='2026-09')
    assert result == [{'date': '2026-09-17', 'count': 1}]
    assert instructions < 20000


def test_fold_selection_remains_global_across_cursor_filter(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    first = {**row('first', event='2026-09-17T01:00:00Z'), 'content_hash': 'same'}
    later = {**row('later', event='2026-09-17T02:00:00Z'), 'content_hash': 'same'}
    store.import_rows([later, first])
    assert store.list_messages(after=store.cursor(first)) == []
    store.import_rows([{**first, 'deleted_at': '2026-09-17T03:00:00Z'}])
    assert [r['id'] for r in store.list_messages()] == ['later']


def test_search_limit_matches_cloud_cap(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row(f'{i:04}', '沈予') for i in range(250)])
    hits = store.search('沈予', limit=500)
    assert hits['count'] == 200 and hits['has_more']
    tail = store.search('沈予', limit=500, cursor=hits['next_cursor'])
    assert tail['count'] == 50 and not tail['has_more']
    # Ordinary archive pages still have their separate 1000-row cap.
    assert len(store.list_messages(limit=500)) == 250


@pytest.mark.parametrize('needle,text', [
    ('k', 'K'), ('s', 'ſ'), ('i', 'İ'), ('i', 'ı'), ('é', 'É'),
    ('É沈予', 'é沈予'), ('沈予', 'prefix\x00沈予'), ('a_b', 'A_B'),
])
def test_search_prefilter_never_narrows_regex_unicode_semantics(tmp_path, needle, text):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row('hit', text), row('miss', '无关')])
    hits = store.search(needle)
    assert re.search(re.escape(needle), text, re.IGNORECASE)
    assert [r['id'] for r in hits['results']] == ['hit']


def test_chinese_search_prefilter_avoids_python_callback_for_non_candidates(tmp_path, monkeypatch):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row(f'miss-{i}', '其他内容') for i in range(1000)] + [row('hit', '沈予')])
    callbacks = [0]
    connect = sqlite3.connect
    class CountingConnection(sqlite3.Connection):
        def create_function(self, name, narg, func, **kwargs):
            if name == 'archive_literal':
                original = func
                def func(value):
                    callbacks[0] += 1
                    return original(value)
            return super().create_function(name, narg, func, **kwargs)
    monkeypatch.setattr(archive_module.sqlite3, 'connect',
                        lambda *args, **kwargs: connect(*args, **kwargs, factory=CountingConnection))
    assert store.search('沈予')['count'] == 1
    assert callbacks[0] < 10


def test_cold_wal_file_without_sidecars_reopens_in_fresh_process(tmp_path):
    db = tmp_path / 'archive.db'
    created = subprocess.run([sys.executable, '-c',
        'import sys; from shenyu_gateway.local_chat_archive import LocalChatArchive; '
        'LocalChatArchive(sys.argv[1], create=True)', str(db)], cwd=ROOT, capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    assert not Path(str(db) + '-wal').exists()
    assert not Path(str(db) + '-shm').exists()
    reopened = subprocess.run([sys.executable, 'scripts/local_chat_archive.py', '--db', str(db), 'stats'],
                              cwd=ROOT, capture_output=True, text=True)
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout) == {'total': 0, 'active': 0, 'visible': 0}


def test_backup_is_self_contained_rollback_journal_file(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row()])
    target = store.backup(tmp_path / 'backup.db')
    with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as conn:
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    assert LocalChatArchive(target).export_rows() == [row()]


def test_old_sqlite_fails_before_creating_files(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_module.sqlite3, 'sqlite_version_info', (3, 29, 0))
    with pytest.raises(RuntimeError, match='SQLite.*3.30'):
        LocalChatArchive(tmp_path / 'new' / 'archive.db', create=True)
    assert not (tmp_path / 'new').exists()


def test_archive_manual_transaction_is_explicit(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    with store._connect(write=True) as conn:
        assert conn.isolation_level is None
        assert not conn.in_transaction
        conn.execute('BEGIN IMMEDIATE')
        assert conn.in_transaction


@pytest.mark.asyncio
@pytest.mark.parametrize('initial,new', [('supabase','sqlite'), ('sqlite','supabase')])
async def test_inflight_archive_backend_mutation_fails_symmetrically(tmp_path, initial, new):
    runtime = GatewayStore(str(tmp_path / 'runtime.db'))
    local = LocalChatArchive(tmp_path / 'archive.db', create=True)
    cfg = SimpleNamespace(enable_chat_archive=True, chat_archive_backend=initial,
                          chat_archive_db_path=str(local.path), gateway_db_path=str(runtime.db_path))
    class NoCloudWrites:
        async def insert_many(self, *args, **kwargs):
            raise AssertionError('unsupported backend mutation must not silently write cloud')
    service = ChatArchiveService(runtime, NoCloudWrites(), cfg)
    cfg.chat_archive_backend = new
    with pytest.raises(ValueError, match='destination changed'):
        await service.archive_window(session_tag='A', client_name='shenyu-pwa',
                                     messages=[{'role': 'user', 'content': 'new message'}])
    assert local.stats()['total'] == 0


def test_archive_deployment_fields_cannot_be_written_through_config_post(monkeypatch):
    from .test_config_update import _config_client
    import gateway
    fields = {'chat_archive_backend', 'chat_archive_db_path'}
    assert not fields & ConfigUpdate.model_fields.keys()
    before = {f: getattr(gateway.cfg, f) for f in fields}
    client, persisted = _config_client(monkeypatch)
    try:
        response = client.post('/api/config', json={
            'chat_archive_backend': 'sqlite', 'chat_archive_db_path': '/tmp/not-the-archive.db'})
        assert response.status_code == 200
        assert not fields & set(response.json()['changed'])
        assert {f: getattr(gateway.cfg, f) for f in fields} == before
        assert all(not {'CHAT_ARCHIVE_BACKEND', 'CHAT_ARCHIVE_DB_PATH'} & entry.keys() for entry in persisted)
    finally:
        client.close()


def test_verify_is_exact_snapshot_proof_not_health_probe(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.import_rows([row('old')])
    assert store.verify_rows([row('old')])['total'] == 1
    store.append_rows([row('new')])
    with pytest.raises(ValueError, match='ID sets differ'):
        store.verify_rows([row('old')])
    assert store.stats()['total'] == 2
    snapshot = store.export_rows()
    store.soft_delete('old')
    with pytest.raises(ValueError, match='tombstones differ'):
        store.verify_rows(snapshot)


def test_invalid_cursor_id_rejects_entire_import_without_touching_originals(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.import_rows([row('old')])
    with pytest.raises(ValueError, match='cursor-safe'):
        store.import_rows([row('new'), row('bad|id')])
    assert store.export_rows() == [row('old')]


def test_deployment_image_ships_archive_cli_and_checks_sqlite_version():
    dockerfile = (ROOT / 'Dockerfile').read_text()
    assert 'COPY scripts/local_chat_archive.py ./scripts/local_chat_archive.py' in dockerfile
    assert 'sqlite3.sqlite_version_info' in dockerfile


def test_search_zero_limit_also_matches_cloud(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([row('a', '沈予'), row('b', '沈予')])
    assert store.search('沈予', limit=0)['count'] == 1


def test_runtime_db_setting_cannot_indirectly_move_local_archive(monkeypatch, tmp_path):
    from .test_config_update import _config_client
    import gateway
    monkeypatch.setattr(gateway.cfg, 'chat_archive_backend', 'sqlite')
    monkeypatch.setattr(gateway.cfg, 'chat_archive_db_path', '')
    original_path = str(tmp_path / 'current' / 'runtime.db')
    monkeypatch.setattr(gateway.cfg, 'gateway_db_path', original_path)
    initializations = []
    monkeypatch.setattr(gateway, '_init_store', lambda: initializations.append(True))
    client, persisted = _config_client(monkeypatch)
    try:
        result = client.post('/api/config', json={'gateway_db_path': str(tmp_path / 'elsewhere' / 'runtime.db')})
        assert result.status_code == 400
        assert gateway.cfg.gateway_db_path == original_path
        assert not initializations and not persisted
    finally:
        client.close()
