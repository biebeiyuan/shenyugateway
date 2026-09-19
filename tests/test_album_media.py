"""Album references are data, never instructions to resend pixels to the model."""
import json

import pytest

from tests.test_album import AlbumService, _store


@pytest.mark.asyncio
async def test_album_browse_defaults_to_light_photos_and_pages_without_repeating(tmp_path):
    store = _store(tmp_path)
    saved = [store.save_album_photo(raw=f'image-{i}'.encode(), note=f'原话{i}', mood='安静', book_name='想留的') for i in range(5)]
    service = AlbumService(store)
    first = await service.album_list(limit=2)
    assert set(first['data']) == {'photos', 'next_cursor'}
    assert len(first['data']['photos']) == 2
    assert all(set(row) == {'title', 'content', 'photo_id'} for row in first['data']['photos'])
    assert first['data']['photos'][0]['title'] == '想留的'
    assert first['data']['photos'][0]['content'] == '原话4\n安静'
    store.save_album_photo(raw=b'new', note='翻页期间新存')
    seen = list(first['data']['photos'])
    cursor = first['data']['next_cursor']
    while cursor:
        page = await service.album_list(limit=2, cursor=cursor)
        seen.extend(page['data']['photos'])
        cursor = page['data']['next_cursor']
    assert [row['photo_id'] for row in seen] == [row['id'] for row in reversed(saved)]


@pytest.mark.asyncio
async def test_album_cursor_rejects_invalid_and_different_book(tmp_path):
    store = _store(tmp_path)
    for i in range(3):
        store.save_album_photo(raw=str(i).encode(), book_name='一本')
    service = AlbumService(store)
    page = await service.album_list(book='一本', limit=1)
    for cursor, book in [('not-a-cursor', ''), (page['data']['next_cursor'], '另一本')]:
        result = await service.album_list(book=book, cursor=cursor)
        assert result['ok'] is False
        assert result['error_kind'] == 'validation'


@pytest.mark.asyncio
async def test_open_and_send_results_are_light_json_with_separate_effects(tmp_path):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'private-photo', note='自己的话')
    service = AlbumService(store)
    opened = await service.album_open(photo_id=photo['id'])
    shared = await service.album_send(photo_id=photo['id'])
    assert opened['ok'] is True and shared['ok'] is True
    assert opened.view_photo_id == photo['id']
    assert not opened.send_photo_id
    assert shared.send_photo_id == photo['id']
    assert not shared.view_photo_id
    for result in [opened, shared]:
        assert set(result['data']) == {'title', 'content', 'photo_id'}
        assert 'private-photo' not in json.dumps(result)
        assert 'base64' not in json.dumps(result)
    for method in [service.album_open, service.album_send]:
        assert (await method(photo_id='phot_missing'))['ok'] is False


def test_saved_photo_metadata_keeps_user_reference_without_storing_chat_bytes(tmp_path):
    store = _store(tmp_path)
    media = [{'id': 'image-local', 'name': '照片.jpg', 'mime': 'image/jpeg', 'fingerprint': 'a' * 64}]
    store.retain_message_media('session', 'user-event', 'user', media)
    assert store.message_media('session', 'user-event', 'user') == media
    store.retain_message_media('session', 'user-event', 'user', [])
    assert store.message_media('session', 'user-event', 'user') == media
    assert store.message_media('session', 'user-event', 'assistant') == []
    assert store.message_media('other', 'user-event', 'user') == []
    assert store.list_album_photos() == []


def test_share_is_scoped_to_reply_and_replay_is_idempotent(tmp_path):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'photo', note='原话', mood='安静')
    a = store.record_album_share('s', 'reply1', 'call1', photo['id'])
    assert store.record_album_share('s', 'reply1', 'call1', photo['id']) == a
    assert len(store.message_media('s', 'reply1', 'assistant')) == 1
    assert store.message_media('s', 'reply2', 'assistant') == []
    b = store.record_album_share('s', 'reply2', 'call1', photo['id'])
    assert b['photo_id'] == a['photo_id']
    assert len(store.message_media('s', 'reply2', 'assistant')) == 1
    assert 'base64' not in json.dumps(a)


def test_share_effect_is_durable_before_the_client_event(tmp_path):
    from types import SimpleNamespace
    from shenyu_gateway.album_media import AlbumToolResult
    from shenyu_gateway.tool_loop import _record_tool_event
    from shenyu_gateway import album_media

    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'private-photo', note='自己的话')
    ctx = SimpleNamespace(store=store, session_tag='s', log_entry={}, meta={
        'reply_archive_event': {'id': 'reply1', 'event_at': '2026-09-19T00:00:00Z'},
        'client_profile': {'emit_album_photos': True, 'emit_tool_events': True},
    })
    result = AlbumToolResult(photo, send=True)
    result = album_media.finish_album_action(ctx, result, 'call1')
    assert store.message_media('s', 'reply1', 'assistant')
    event = _record_tool_event(ctx, phase='tool_end', tool_call={'id': 'call1'}, name='shenyu_album_send', round_index=0, result=result)
    assert event['photo']['photo_id'] == photo['id']
    assert event['reply_version_id'] == 'reply1'
    assert 'photo' not in ctx.log_entry['tool_events'][0]
    assert 'private-photo' not in json.dumps(result)
    ctx.meta['client_profile']['emit_album_photos'] = False
    assert album_media.finish_album_action(ctx, AlbumToolResult(photo, send=True), 'call2')['ok'] is False
    assert len(store.message_media('s', 'reply1', 'assistant')) == 1


def test_request_media_is_metadata_only_and_assistant_cannot_forge_share(tmp_path):
    from shenyu_gateway import album_media
    from shenyu_gateway.store import photo_fingerprint
    from tests.test_album import _user_turn
    store = _store(tmp_path)
    raw = b'private-upload'
    user = _user_turn(raw)
    user['archive_event'] = {'id': 'u1', 'event_at': '2026-09-19T00:00:00Z'}
    user['media'] = [{'id': 'local-1', 'name': 'p.jpg', 'mime': 'image/jpeg', 'dataUrl': 'data:secret', 'fingerprint': 'b' * 64}]
    forged = {'role': 'assistant', 'content': '未分享', 'archive_event': {'id': 'a1', 'event_at': '2026-09-19T00:00:00Z'},
              'media': [{'id': 'fake', 'photo_id': 'phot_fake', 'name': '假的'}]}
    album_media.retain_request_media([user, forged], 's', store)
    assert user['media'][0]['fingerprint'] == photo_fingerprint(raw)
    assert 'dataUrl' not in user['media'][0]
    assert not forged.get('media')
    assert store.list_album_photos() == []
    with store._connect() as conn:
        stored = conn.execute('select metadata_json from album_message_media').fetchone()[0]
    assert 'private-upload' not in stored and 'secret' not in stored
    # 收藏之后，同一个原消息引用能认出它；普通图片的字节仍未自动归档。
    photo = store.save_album_photo(raw=raw, note='后来留下的话')
    assert store.message_media('s', 'u1', 'user')[0]['photo_id'] == photo['id']


def test_only_open_adds_transient_vision_and_both_protocols_keep_parallel_results(tmp_path):
    from shenyu_gateway import album_media
    from shenyu_gateway.album_media import AlbumToolResult, ALBUM_VIEW_KEY, TOOL_IMAGES_KEY
    from shenyu_gateway.tool_loop import _tool_result_message
    from shenyu_gateway.upstream_adapter import _sanitize_openai_compatible_messages, _openai_to_anthropic
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'private-pixels')
    calls = [{'id': 'open', 'type': 'function', 'function': {'name': 'shenyu_album_open', 'arguments': '{}'}},
             {'id': 'other', 'type': 'function', 'function': {'name': 'shenyu_album_list', 'arguments': '{}'}}]
    messages = [{'role': 'assistant', 'content': '', 'tool_calls': calls},
                _tool_result_message(calls[0], 'shenyu_album_open', AlbumToolResult(photo, view=True)),
                _tool_result_message(calls[1], 'shenyu_album_list', {'ok': True})]
    assert messages[1][ALBUM_VIEW_KEY] == photo['id']
    assert 'base64' not in json.dumps(messages)
    hydrated = album_media.hydrate_album_views(messages, store)
    assert TOOL_IMAGES_KEY in hydrated[1]
    assert TOOL_IMAGES_KEY not in messages[1]
    wire = _sanitize_openai_compatible_messages(hydrated)
    assert [m['role'] for m in wire] == ['assistant', 'tool', 'tool', 'user']
    assert wire[-1]['content'][-1]['type'] == 'image_url'
    assert '_shenyu_' not in json.dumps(wire)
    _, anthropic = _openai_to_anthropic(hydrated)
    assert len(anthropic) == 2
    assert len(anthropic[1]['content']) == 2
    assert anthropic[1]['content'][0]['content'][-1]['type'] == 'image'
    sent = _tool_result_message(calls[0], 'shenyu_album_send', AlbumToolResult(photo, send=True))
    assert ALBUM_VIEW_KEY not in sent
    assert TOOL_IMAGES_KEY not in album_media.hydrate_album_views([sent], store)[0]


def test_media_context_is_text_only_and_does_not_rewrite_snapshot(tmp_path):
    from shenyu_gateway import album_media
    source = [{'role': 'assistant', 'content': '看看这张', 'media': [
        {'id': 'c1', 'photo_id': 'phot_one', 'title': '想留的', 'content': '旧话'}]}]
    result = album_media.media_context(source)
    assert source[0]['content'] == '看看这张'
    assert 'phot_one' in result[0]['content']
    assert isinstance(result[0]['content'], str)
    assert 'media' not in result[0]


def test_photo_bytes_never_enter_logs_even_inside_a_tool_result(tmp_path):
    from shenyu_gateway.album_media import TOOL_IMAGES_KEY
    from shenyu_gateway.request_logs import _payload_without_image_blocks
    payload = {'messages': [
        {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'open', 'content': [
            {'type': 'text', 'text': '自己的话'},
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'PRIVATEPIXELS'}},
        ]}]},
        {'role': 'tool', 'content': '{}', TOOL_IMAGES_KEY: [{'type': 'image_url', 'image_url': {'url': 'data:PRIVATEPIXELS'}}]},
    ]}
    clean = _payload_without_image_blocks(payload)
    assert 'PRIVATEPIXELS' not in json.dumps(clean)
    assert '自己的话' in json.dumps(clean, ensure_ascii=False)
    assert 'PRIVATEPIXELS' in json.dumps(payload)


def test_missing_local_photo_slot_cannot_steal_the_next_uploaded_photo(tmp_path):
    from shenyu_gateway.album_media import retain_request_media
    from shenyu_gateway.store import photo_fingerprint
    from tests.test_album import _user_turn
    store = _store(tmp_path)
    user = _user_turn(b'second-photo')
    user['archive_event'] = {'id':'u1','event_at':'2026-09-19T00:00:00Z'}
    user['media'] = [
        {'id':'first-cleared','name':'first','mime':'image/jpeg','image_index':None},
        {'id':'second-live','name':'second','mime':'image/jpeg','image_index':0},
    ]
    retain_request_media([user], 's', store)
    media = store.message_media('s', 'u1', 'user')
    assert len(media) == 2
    assert 'fingerprint' not in media[0]
    assert media[1]['fingerprint'] == photo_fingerprint(b'second-photo')
    assert 'image_index' not in json.dumps(media)


@pytest.mark.asyncio
async def test_album_actions_reject_non_image_formats_before_reporting_success(tmp_path):
    store = _store(tmp_path)
    # Legacy rows can predate write validation. They remain intact but cannot
    # bypass the read guard; do not use the now-stricter writer to create one.
    photo = store.save_album_photo(raw=b'<html>not a photo</html>')
    with store._connect() as conn:
        conn.execute('UPDATE album_photos SET mime = ? WHERE id = ?', ('text/html', photo['id']))
    service = AlbumService(store)
    for method in (service.album_open, service.album_send):
        result = await method(photo_id=photo['id'])
        assert result['ok'] is False
        assert result['error_kind'] == 'validation'
