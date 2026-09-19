"""Review regressions: image failures must not masquerade as successful actions."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
from pathlib import Path
import sqlite3
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from shenyu_gateway.album_media import AlbumToolResult, finish_album_action
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.context_snapshots import write_completion_context_snapshot
from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.sessions import SessionManager
from shenyu_gateway.tool_loop import _execute_internal_tool_call, _tool_result_message
from shenyu_gateway.tool_registry import execute_gateway_tool
from tests.test_album import AlbumService, _store
from tests.test_album_delivery import client_for
from tests.test_gateway_streaming import _nonstream_tool_loop_ctx


def album_context(store):
    cfg = RuntimeConfig()
    ctx = _nonstream_tool_loop_ctx([], max_rounds=5, assistant_outputs=[])
    ctx.cfg, ctx.store = cfg, store
    ctx.sessions = SessionManager(store, cfg)
    ctx.meta = {
        'session': store.get_or_create_session('s', 'shenyu-pwa'),
        'reply_archive_event': {'id': 'reply', 'event_at': '2026-09-19T00:00:00Z'},
        'client_profile': {'emit_album_photos': True, 'emit_tool_events': True},
    }
    service = GatewayToolService(runtime_config=cfg, store=store, supabase=None)
    ctx.execute_gateway_tool = partial(execute_gateway_tool, service=service)
    return ctx


def album_call(action, photo_id, call_id, mode='direct'):
    name, args = f'shenyu_album_{action}', {'photo_id': photo_id}
    if mode != 'direct':
        target = name if mode == 'broker' else f'album_{action}'
        name, args = 'shenyu_gateway_tool', {'tool': target, 'params': args}
    return {'id': call_id, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}


@pytest.mark.parametrize('reason', ['limit', 'conflict', 'missing'])
def test_share_business_errors_preserve_the_actual_reason(tmp_path, reason):
    store = _store(tmp_path)
    ctx = album_context(store)
    photo = store.save_album_photo(raw=b'photo')
    if reason == 'limit':
        for i in range(9):
            store.record_album_share('s', 'reply', f'old-{i}', photo['id'])
        expected = '九张照片'
    elif reason == 'conflict':
        other = store.save_album_photo(raw=b'other')
        store.record_album_share('s', 'reply', 'new', other['id'])
        expected = '另一张照片'
    else:
        photo = {**photo, 'id': 'phot_missing'}
        expected = '不在相册'
    result = finish_album_action(ctx, AlbumToolResult(photo, send=True), 'new')
    assert result['ok'] is False
    assert result['error_kind'] == 'validation'
    assert expected in result['error']
    assert '请再试一次' not in result['error']
    assert not ctx.meta.get('album_shared_media')


def test_share_storage_failure_is_still_an_exception_not_false_success(tmp_path, monkeypatch):
    store = _store(tmp_path)
    ctx = album_context(store)
    photo = store.save_album_photo(raw=b'photo')

    def unavailable(*args):
        raise sqlite3.OperationalError('simulated ledger failure')

    monkeypatch.setattr(store, 'record_album_share', unavailable)
    result = finish_album_action(ctx, AlbumToolResult(photo, send=True), 'new')
    assert result['ok'] is False and result['error_kind'] == 'exception'
    assert not ctx.meta.get('album_shared_media')
    assert store.message_media('s', 'reply', 'assistant') == []


@pytest.mark.asyncio
async def test_cached_failure_does_not_turn_into_outer_success(tmp_path):
    ctx = album_context(_store(tmp_path))
    call = {'id': 'bad-page', 'function': {'name': 'shenyu_album_list',
            'arguments': json.dumps({'cursor': 'invalid'})}}
    cache = {}
    first, *_ = await _execute_internal_tool_call(ctx, call, cache, log_label='test')
    second, _, _, cached, _ = await _execute_internal_tool_call(ctx, call, cache, log_label='test')
    assert first['ok'] is False
    assert cached is True
    assert second['ok'] is False
    assert second['error_kind'] == first['error_kind']
    assert second['error'] == first['error']


@pytest.mark.asyncio
async def test_cache_keeps_legacy_non_dict_results_wrappable(tmp_path):
    ctx = album_context(_store(tmp_path))

    async def legacy_result(*args, **kwargs):
        return ['legacy value']

    ctx.execute_gateway_tool = legacy_result
    call = {'id': 'legacy', 'function': {'name': 'shenyu_album_list', 'arguments': '{}'}}
    cache = {}
    await _execute_internal_tool_call(ctx, call, cache, log_label='test')
    result, _, _, cached, _ = await _execute_internal_tool_call(ctx, call, cache, log_label='test')
    assert cached is True
    assert result == {'ok': True, 'cached_duplicate': True, 'result': ['legacy value']}


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['direct', 'broker', 'short-broker'])
@pytest.mark.parametrize('action', ['open', 'send'])
async def test_each_explicit_album_action_keeps_its_effect(tmp_path, mode, action):
    from shenyu_gateway.album_media import ALBUM_VIEW_KEY
    from shenyu_gateway.tool_loop import _record_tool_event

    store = _store(tmp_path)
    ctx = album_context(store)
    photo = store.save_album_photo(raw=b'photo')
    cache = {}
    for call_id in ['first', 'second']:
        call = album_call(action, photo['id'], call_id, mode)
        result, _, name, cached, _ = await _execute_internal_tool_call(ctx, call, cache, log_label='test')
        assert cached is False
        assert isinstance(result, AlbumToolResult)
        if action == 'open':
            assert _tool_result_message(call, name, result)[ALBUM_VIEW_KEY] == photo['id']
        else:
            event = _record_tool_event(ctx, phase='tool_end', tool_call=call,
                                       name=name, round_index=0, result=result)
            assert event['target_tool'] == 'shenyu_album_send'
            assert event['photo']['id'] == call_id
    if action == 'send':
        assert [m['id'] for m in store.message_media('s', 'reply', 'assistant')] == ['first', 'second']
        # A replay keeps the same delivery identity, not an extra copy.
        await _execute_internal_tool_call(ctx, call, cache, log_label='test')
        assert len(store.message_media('s', 'reply', 'assistant')) == 2
        assert len(ctx.meta['album_shared_media']) == 2


@pytest.mark.parametrize('mime', ['text/html', 'image/svg+xml', 'image/bmp'])
def test_unsupported_mime_is_rejected_before_creating_any_album_row(tmp_path, mime):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match='格式'):
        store.save_album_photo(raw=b'not-supported', mime=mime)
    assert store.list_album_books() == []
    assert store.list_album_photos() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('mime, canonical', [
    (' Image/PNG ', 'image/png'), ('IMAGE/JPEG', 'image/jpeg'),
    ('image/webp; charset=binary', 'image/webp'), ('image/gif', 'image/gif'),
])
async def test_saved_mime_is_canonical_and_immediately_usable(tmp_path, mime, canonical):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'pixels-unchanged', mime=mime)
    assert photo['mime'] == canonical
    stored = store.album_photo_bytes(photo['id'])
    assert stored['mime'] == canonical and stored['bytes'] == b'pixels-unchanged'
    service = AlbumService(store)
    assert (await service.album_open(photo['id']))['ok'] is True
    assert (await service.album_send(photo['id']))['ok'] is True


def test_media_writes_do_not_depend_on_the_number_of_table_columns(tmp_path):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'photo')
    with store._connect() as conn:
        conn.execute('ALTER TABLE album_message_media ADD COLUMN future_field TEXT')
    store.retain_message_media('s', 'u', 'user', [{'id': 'upload', 'fingerprint': 'a' * 64}])
    store.record_album_share('s', 'reply', 'share', photo['id'])
    assert store.message_media('s', 'u', 'user')[0]['id'] == 'upload'
    assert store.message_media('s', 'reply', 'assistant')[0]['photo_id'] == photo['id']


def test_concurrent_creation_of_one_book_returns_the_same_book_without_error(tmp_path, monkeypatch):
    store = _store(tmp_path)
    lookup = store._album_book_row
    both_absent = Barrier(2)

    def lookup_together(conn, name):
        row = lookup(conn, name)
        if row is None:
            both_absent.wait(timeout=5)
        return row

    monkeypatch.setattr(store, '_album_book_row', lookup_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        books = list(pool.map(store.ensure_album_book, ['同一本', '同一本']))
    assert books[0] == books[1]
    assert len(store.list_album_books()) == 1
    photo = store.save_album_photo(raw=b'keep', book_name='同一本')
    assert store.ensure_album_book('同一本')['id'] == books[0]['id']
    assert store.album_photo_bytes(photo['id'])['bytes'] == b'keep'


def fail_media_lookup(*args, **kwargs):
    raise sqlite3.OperationalError('simulated media-only failure')


def test_media_failure_does_not_block_text_history_or_reply_recovery(tmp_path, monkeypatch):
    store = _store(tmp_path)
    session = store.get_or_create_session('s', 'shenyu-pwa')
    store.append_message(session['id'], 'user', '原来的问题')
    store.append_message(session['id'], 'assistant', '原来的回答',
                         source_table='reply_version', source_id='reply')
    monkeypatch.setattr(store, 'message_media_batch', fail_media_lookup)
    client = TestClient(client_for(store).app, raise_server_exceptions=False)
    history = client.get('/api/gateway/sessions/s')
    assert history.status_code == 200
    assert history.json()['recent_messages'][-1]['content'] == '原来的回答'
    recovery = client.get('/api/gateway/sessions/s/reply-recovery')
    assert recovery.status_code == 200
    assert recovery.json()['replies'][0]['content'] == '原来的回答'


def test_media_failure_does_not_block_writing_the_completed_text_snapshot(tmp_path, monkeypatch):
    store = _store(tmp_path)
    ctx = album_context(store)
    ctx.meta['snapshot_messages'] = [{'role': 'user', 'content': '问题'}]
    monkeypatch.setattr(store, 'message_media_batch', fail_media_lookup)
    result = write_completion_context_snapshot(store, ctx.meta, '完整回答')
    assert result['messages'][-1]['content'] == '完整回答'
    assert result['messages'][-1]['archive_event']['id'] == 'reply'


@pytest.mark.parametrize('broken', ['message_media_batch', 'album_notes_by_fingerprints'])
def test_resolver_failure_is_retryable_not_a_successful_empty_album(tmp_path, monkeypatch, broken):
    store = _store(tmp_path)
    monkeypatch.setattr(store, broken, fail_media_lookup)
    client = TestClient(client_for(store).app, raise_server_exceptions=False)
    response = client.post('/api/gateway/album/resolve', json={
        'session_tag': 's', 'events': [], 'fingerprints': ['a' * 64],
    })
    assert response.status_code == 503
    assert '重试' in response.json()['detail']


SLOT_CONTRACT = json.loads((Path(__file__).parent / 'fixtures/album_media_slots.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', SLOT_CONTRACT['cases'], ids=lambda case: '-'.join(case['order']))
def test_shared_pwa_wire_fixture_resolves_the_correct_photo_and_note(tmp_path, case):
    from copy import deepcopy
    from shenyu_gateway.album_media import retain_request_media

    store = _store(tmp_path)
    photos = {key: store.save_album_photo(raw=raw.encode(), note=f'{key} 的备注')
              for key, raw in SLOT_CONTRACT['raw'].items()}
    user = deepcopy(case['wire'])
    retain_request_media([user], 's', store)
    actual = store.message_media('s', user['archive_event']['id'], 'user')
    assert [item['id'] for item in actual] == case['order']
    for item in actual:
        expected = photos.get(item['id'])
        if expected:
            assert item['photo_id'] == expected['id']
            assert item['fingerprint'] == expected['fingerprint']
            assert item['content'] == expected['note']
        else:
            assert 'photo_id' not in item and 'fingerprint' not in item
    assert 'image_index' not in json.dumps(actual)


def test_metadata_only_user_restore_is_fingerprint_driven_not_client_photo_id(tmp_path):
    from shenyu_gateway.album_media import retain_request_media
    store = _store(tmp_path)
    saved = store.save_album_photo(raw=b'saved', note='当时写的')
    user = {'role': 'user', 'content': '旧记录只有文字',
            'archive_event': {'id': 'old-user', 'event_at': '2026-09-19T00:00:00Z'},
            'media': [{'id': 'local', 'fingerprint': saved['fingerprint'],
                       'photo_id': 'phot_forged', 'content': '伪造备注'}]}
    retain_request_media([user], 's', store)
    assert user['media'][0]['photo_id'] == saved['id']
    assert user['media'][0]['content'] == '当时写的'
    assert len(store.list_album_photos()) == 1
