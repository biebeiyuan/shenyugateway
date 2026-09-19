"""Exact share identities and mixed-tool recovery keep pixels out of storage."""
import asyncio
import base64
from copy import deepcopy
import json
import sqlite3
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from shenyu_gateway import album_media, prepare_messages as preparation
from shenyu_gateway.album_media import AlbumToolResult, ALBUM_VIEW_KEY, TOOL_IMAGES_KEY, finish_album_action
from shenyu_gateway.chat_archive import parse_archive_event
from shenyu_gateway.context_builder import ContextBuilder
from shenyu_gateway.context_snapshots import write_completion_context_snapshot
from shenyu_gateway.schemas import ChatRequest
from shenyu_gateway.tool_loop import _record_tool_event, _execute_mixed_gateway_tool_calls
from shenyu_gateway.upstream_client import build_upstream_request, resolve_upstream
from tests.test_album import _store, _user_turn
from tests.test_album_review import album_context, album_call
from tests.test_archive_identity import setup_archive, message

@pytest.mark.parametrize('ident', ['reply', ' reply ', '\treply\n', 'reply-中文', 'x' * 160])
def test_share_receipt_keeps_exact_id_even_for_whitespace(tmp_path, ident):
    store = _store(tmp_path)
    ctx = album_context(store)
    raw_event = {'id': ident, 'event_at': '2026-09-19T08:00:00+08:00'}
    parsed = parse_archive_event(raw_event)
    assert parsed['id'] == ident
    assert parsed['event_at'] != raw_event['event_at']
    ctx.meta['reply_archive_event'] = raw_event  # Stronger than real entry: skip its normalization.
    photo = store.save_album_photo(raw=b'fixture pixels')
    result = finish_album_action(ctx, AlbumToolResult(photo, send=True), 'call-share')
    event = _record_tool_event(ctx, phase='tool_end', tool_call={'id':'call-share'},
                               name='shenyu_album_send', round_index=0, result=result)
    assert result['ok'] is True
    assert event['reply_version_id'] == parsed['id']
    assert store.message_media('s', ident, 'assistant')[0]['photo_id'] == event['photo']['photo_id']


@pytest.mark.parametrize('raw', [None, '{"id":"reply","event_at":"2026-09-19T00:00:00Z"}',
                                [], {'id':5,'event_at':'2026-09-19T00:00:00Z'}])
def test_non_dict_or_invalid_envelope_cannot_reach_successful_share(tmp_path, raw):
    store = _store(tmp_path)
    ctx = album_context(store)
    ctx.meta['reply_archive_event'] = raw
    photo = store.save_album_photo(raw=b'p')
    assert parse_archive_event(raw) is None
    result = finish_album_action(ctx, AlbumToolResult(photo, send=True), 'call')
    assert result['ok'] is False
    event = _record_tool_event(ctx, phase='tool_end', tool_call={'id':'call'},
                               name='shenyu_album_send', round_index=0, result=result)
    assert 'photo' not in event and 'reply_version_id' not in event


@pytest.mark.parametrize('failed', ['none','write','read'])
def test_explicit_slots_obey_nine_item_bound_even_when_ledger_fails(tmp_path, monkeypatch, failed):
    store = _store(tmp_path)
    user = _user_turn(*[f'image {i}'.encode() for i in range(9)])
    user['archive_event'] = {'id':'u1','event_at':'2026-09-19T00:00:00Z'}
    user['media'] = [{'id':f'bad-{i}', 'name':'photo', 'mime':'image/jpeg', 'image_index':20+i}
                     for i in range(9)]
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError(f'review simulated {failed} failure')
    if failed == 'write':
        monkeypatch.setattr(store, 'retain_message_media', broken)
    if failed == 'read':
        monkeypatch.setattr(store, 'message_media_batch', broken)
    album_media.retain_request_media([user], 's', store)
    assert len(user['media']) == 9
@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', ['openai','anthropic'])
@pytest.mark.parametrize('room', [False, True])
@pytest.mark.parametrize('available', [True, False])
async def test_real_mixed_handoff_then_prepare_never_persists_view_pixels(tmp_path, monkeypatch, protocol, room, available):
    archive, store, archive_service = setup_archive(tmp_path)
    ctx = album_context(store)
    cfg = ctx.cfg
    cfg.enable_chat_archive = True
    cfg.chat_archive_backend = 'sqlite'
    cfg.chat_archive_db_path = str(archive.path)
    cfg.gateway_db_path = str(store.db_path)
    cfg.max_client_messages = 40
    cfg.epoch_reset_on_cold_cache = False
    cfg.enable_room_mode = room
    cfg.enable_cold_start = False
    cfg.client_tool_surface = 'all'
    cfg.inject_conflict_shelf = False
    raw = b'R2-MIXED-PRIVATE-PIXELS-ONLY-IN-PROVIDER-INPUT'
    encoded = base64.b64encode(raw).decode()
    photo = store.save_album_photo(raw=raw, mime='image/png')
    opening = album_call('open', photo['id'], 'open-1')
    local = {'id':'client-1','type':'function','function':{'name':'read_file','arguments':'{}'}}
    completion = {'choices':[{'message':{'role':'assistant','content':'', 'tool_calls':[opening,local]}}]}
    await _execute_mixed_gateway_tool_calls(ctx, completion, [opening,local])
    pending_before = deepcopy(store.find_pending_gateway_tool_turn(ctx.session_id, ['client-1']))
    assert ALBUM_VIEW_KEY in json.dumps(pending_before)
    assert encoded not in json.dumps(pending_before)
    assert TOOL_IMAGES_KEY not in json.dumps(pending_before)
    history = [message('u1', '【窗边 · 19/09 08:00】' if room else '看这张照片', 'user'),
               completion['choices'][0]['message'],
               {'role':'tool','tool_call_id':'client-1','name':'read_file','content':'fixture client result'}]
    builder = ContextBuilder(store, ctx.sessions, None, cfg=cfg, supabase_client=None,
                             stable_charter_block=lambda:'fixed test charter')
    async def normal_package(session, **kwargs):
        return {'stable_charter':'fixed test charter','heartbeat_digest':'',
                'heartbeat_pending_ids':[],'calendar_context':{}}
    monkeypatch.setattr(builder,'build_context_package',normal_package)
    # Use the actual room builder; no Supabase client, and no external MCP work.
    monkeypatch.setattr(preparation._mcp_registry,'ensure_fresh',AsyncMock())
    reads = []
    original = store.album_photo_bytes
    def read(pid):
        reads.append(pid)
        if not available:
            raise sqlite3.OperationalError('fixture missing photo bytes')
        return original(pid)
    monkeypatch.setattr(store, 'album_photo_bytes', read)
    deps = preparation.PrepareMessagesDeps(cfg=cfg, store=store, supabase_client=None,
        context_builder_factory=lambda *args:builder, client_name_from_request=lambda req:'test-client',
        session_tag_from_request=lambda *a,**kw:'s', resolve_upstream=lambda:{**resolve_upstream(cfg),'protocol':protocol},
        maybe_prepare_cold_start_snapshot=lambda *a:None, prune_runtime_state=lambda *a:{})
    envelope = {'id':' reply-next ', 'event_at':'2026-09-19T08:00:00+08:00'}
    body = ChatRequest(model='fixture', messages=history,
                       metadata={'reply_version_id':envelope['id'],'reply_archive_event':envelope})
    req = Request({'type':'http','headers':[]})
    prepared, meta = await preparation.prepare_messages(req, body, deps)
    await asyncio.gather(*tuple(preparation._BACKGROUND_TASKS))
    assert meta['reply_archive_event'] == parse_archive_event(envelope)
    assert meta['reply_archive_event'] is not envelope
    assert meta['pending_gateway_tool_turn_ids'] == [pending_before['id']]
    assert bool(meta.get('is_room')) is room
    assert reads == [photo['id']]
    assert (encoded in json.dumps(prepared)) is available
    assert ALBUM_VIEW_KEY not in json.dumps(prepared)
    assert encoded not in json.dumps(meta)
    assert TOOL_IMAGES_KEY not in json.dumps(meta)
    payload, *_ = await build_upstream_request(req, body, messages_override=prepared, meta=meta, cfg=cfg)
    assert (encoded in json.dumps(payload)) is available
    assert ALBUM_VIEW_KEY not in json.dumps(payload) and TOOL_IMAGES_KEY not in json.dumps(payload)
    # A complete reply writes a second snapshot from the pre-hydration base.
    write_completion_context_snapshot(store, meta, 'fixture complete reply')
    pending_after = store.find_pending_gateway_tool_turn(ctx.session_id, ['client-1'])
    assert pending_after == pending_before
    persisted = {
        'snapshots':store.get_recent_context_snapshots(ctx.session_id, 10),
        'raw_windows':store.get_recent_raw_request_windows(ctx.session_id, 10),
        'messages':store.get_recent_messages(ctx.session_id, 50),
        'pending':pending_after, 'archive':archive.export_rows(),
    }
    # BLOBs saved deliberately in album_photos are not the transcript.
    assert encoded not in json.dumps(persisted)
    assert TOOL_IMAGES_KEY not in json.dumps(persisted)
