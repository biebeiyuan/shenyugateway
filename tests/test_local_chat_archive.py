from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


def storage_module():
    name = 'shenyu_gateway.local_chat_archive'
    assert importlib.util.find_spec(name) is not None, 'local archive storage is not implemented'
    return __import__(name, fromlist=['LocalChatArchive'])


def row(i='one', content='今天和沈予聊天', *, session='7.18', event='2026-09-17T01:00:00+00:00', **extra):
    return dict(id=i, session_tag=session, thread=session, client_name='shenyu-pwa',
                role='user', content=content, content_hash='hash-' + i,
                event_at=event, archived_at='2026-09-17T01:00:01+00:00', deleted_at=None, **extra)


def make_store(tmp_path):
    return storage_module().LocalChatArchive(tmp_path / 'archive.db', create=True)


def test_storage_exists():
    storage_module()


def test_import_preserves_original_and_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    original = row(content='  原文\n一字不改🙂  ')
    assert store.import_rows([original]) == 1
    assert store.import_rows([original]) == 0
    assert store.export_rows() == [original]
    assert store.stats()['total'] == 1


def test_import_conflict_rolls_back_whole_batch(tmp_path):
    store = make_store(tmp_path)
    store.import_rows([row()])
    with pytest.raises(ValueError, match='conflict'):
        store.import_rows([row('new'), {**row(), 'content': 'changed'}])
    assert store.export_rows() == [row()]


def test_distinct_ids_with_same_words_are_retained(tmp_path):
    store = make_store(tmp_path)
    store.append_rows([{**row('a','嗯'), 'content_hash':'same'},
                       {**row('b','嗯'), 'content_hash':'same'}])
    assert len(store.list_messages()) == 2
    assert store.search('嗯')['count'] == 2


def test_legacy_fold_preserves_raw_rows_and_tombstones(tmp_path):
    store = make_store(tmp_path)
    a = row('a'); b = {**row('b', session='new'), 'content_hash':a['content_hash']}
    gone = {**row('gone'), 'deleted_at': '2026-09-17T02:00:00+00:00'}
    store.import_rows([a,b,gone])
    assert len(store.export_rows()) == 3
    assert len(store.list_messages()) == 1
    assert store.stats() == {'total':3,'active':2,'visible':1}
    assert store.soft_delete(store.list_messages()[0]['id']) == 2
    assert not store.list_messages()
    # A repeat import must not revive an explicitly deleted local row.
    store.import_rows([a,b,gone])
    assert not store.list_messages()


def test_date_order_and_a_b_a_are_independent_of_source_thread(tmp_path):
    store = make_store(tmp_path)
    store.append_rows([row('1',session='A'), row('2',session='B',event='2026-09-17T10:00:00+08:00'),
                       row('3',session='A',event='2026-09-17T03:00:00Z')])
    result=store.list_messages(limit=10)
    assert [r['id'] for r in result] == ['1','2','3']
    assert [r['session_tag'] for r in result] == ['A','B','A']
    assert store.days('2026-09') == [{'date':'2026-09-17','count':3}]


def test_pagination_filters_before_limit_for_shared_timestamps(tmp_path):
    store=make_store(tmp_path)
    store.append_rows([row(f'{i:04d}') for i in range(137)])
    seen=[]; before=None
    while True:
        rows=store.list_messages(before=before,limit=7)
        if not rows: break
        seen.extend(r['id'] for r in rows)
        before=store.cursor(rows[0])
    assert len(seen)==137 and len(set(seen))==137
    assert set(seen)=={f'{i:04d}' for i in range(137)}
    first=store.list_messages(date='2026-09-17',limit=7)
    rest=store.list_messages(after=store.cursor(first[-1]),limit=7)
    assert [r['id'] for r in rest]==[f'{i:04d}' for i in range(7,14)]


@pytest.mark.parametrize('needle',['沈','沈予','🙂','100%','a_b','*','"','\\','[x]',"'; DROP TABLE archive_messages; --"])
def test_literal_search_has_no_wildcards_and_supports_short_chinese(tmp_path,needle):
    store=make_store(tmp_path)
    store.append_rows([row('hit','前面 '+needle+' 后面'),row('miss','无关文字')])
    result=store.search(needle)
    assert result['count']==1
    assert result['results'][0]['id']=='hit'
    assert result['results'][0]['snippet_match']==needle
    assert store.stats()['total']==2


def test_search_pagination_case_insensitive_and_soft_deleted(tmp_path):
    store=make_store(tmp_path)
    store.append_rows([row(f'{i:03d}', 'Hello 沈予') for i in range(25)])
    store.soft_delete('024')
    seen=[]; cursor=None
    while True:
        result=store.search('hELLo',limit=4,cursor=cursor)
        seen.extend(r['id'] for r in result['results'])
        if not result['has_more']: break
        cursor=result['next_cursor']
    assert len(seen)==24 and len(set(seen))==24 and '024' not in seen


def test_empty_and_invalid_queries_are_explicit(tmp_path):
    store=make_store(tmp_path)
    assert store.search('  ')['results']==[]
    for cursor in ('bad','2026-09-17T00:00:00Z||id','2026-09-17T00:00:00Z|oops|id'):
        with pytest.raises(ValueError): store.list_messages(before=cursor)
    with pytest.raises(ValueError): store.days('2026-99')


def test_no_runtime_retention_or_session_delete_dependency(tmp_path):
    from shenyu_gateway.store import GatewayStore
    store=make_store(tmp_path)
    store.append_rows([row(str(i)) for i in range(1601)])
    runtime=GatewayStore(str(tmp_path/'runtime.db'))
    runtime.get_or_create_session('7.18','shenyu-pwa')
    runtime.prune_runtime_state(message_retention=50)
    runtime.dedupe_messages()
    assert store.stats()['total']==1601
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('PRAGMA foreign_key_list(archive_messages)').fetchall()==[]


def test_backup_uses_consistent_snapshot_and_never_overwrites(tmp_path):
    store=make_store(tmp_path)
    store.append_rows([row()])
    destination=tmp_path/'backups'/'archive.db'
    store.backup(destination)
    restored=storage_module().LocalChatArchive(destination)
    assert restored.export_rows()==[row()]
    with pytest.raises(FileExistsError): store.backup(destination)
    with pytest.raises(ValueError): store.backup(store.path)
    assert destination.stat().st_mode & 0o077 == 0


def test_missing_file_not_created_on_read_and_wrong_database_rejected(tmp_path):
    module=storage_module()
    missing=tmp_path/'missing.db'
    with pytest.raises(FileNotFoundError): module.LocalChatArchive(missing)
    assert not missing.exists()
    other=tmp_path/'runtime.db'
    with sqlite3.connect(other) as conn: conn.execute('CREATE TABLE config_overrides(secret TEXT)')
    with pytest.raises(ValueError): module.LocalChatArchive(other,create=True)


def test_non_dialogue_content_is_rejected_not_silently_archived(tmp_path):
    store=make_store(tmp_path)
    with pytest.raises(ValueError): store.append_rows([{**row(), 'role':'tool'}])
    with pytest.raises(ValueError): store.append_rows([{**row(), 'event_at':'not-a-time'}])
    assert store.stats()['total']==0
