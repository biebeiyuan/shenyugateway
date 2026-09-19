"""HTTP and snapshot contracts for durable, reference-only photo delivery."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shenyu_gateway.context_snapshots import write_completion_context_snapshot
from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router
from tests.test_album import _store


def client_for(store):
    app = FastAPI()
    app.include_router(build_gateway_admin_router(GatewayAdminRouteDeps(
        cfg=SimpleNamespace(gateway_key='', gateway_message_retention=100),
        get_supabase_client=lambda: None, get_session_store=lambda: store,
        require_session_store=lambda: store, context_builder=lambda *a: None,
        resolve_upstream=lambda: {}, prune_runtime_state=lambda **k: {},
        cold_start_idle_minutes=lambda s: 0.0, now=lambda: None, request_logs=[],
    )))
    return TestClient(app)


def test_completion_snapshot_retains_share_on_exact_reply_even_without_text(tmp_path):
    store = _store(tmp_path)
    session = store.get_or_create_session('s', 'shenyu-pwa')
    photo = store.save_album_photo(raw=b'private-photo', note='以前写的')
    share = store.record_album_share('s', 'reply1', 'call1', photo['id'])
    base = [{'role': 'user', 'content': '发我看看', 'archive_event': {'id': 'u1', 'event_at': '2026-09-19T00:00:00Z'}}]
    meta = {'session': session, 'snapshot_messages': base,
            'reply_archive_event': {'id': 'reply1', 'event_at': '2026-09-19T00:00:01Z'}}
    result = write_completion_context_snapshot(store, meta, '')
    assert result['messages'][-1]['role'] == 'assistant'
    assert result['messages'][-1]['media'] == [share]
    assert result['messages'][-1]['archive_event']['id'] == 'reply1'
    assert len(base) == 1
    meta['reply_archive_event']['id'] = 'other-reply'
    other = write_completion_context_snapshot(store, meta, '别的回复')
    assert not other['messages'][-1].get('media')


def test_resolver_returns_saved_fallback_and_inflight_share_without_any_pixels(tmp_path):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'private-photo', note='以前写的')
    store.record_album_share('s', 'reply1', 'call1', photo['id'])
    client = client_for(store)
    result = client.post('/api/gateway/album/resolve', json={
        'session_tag': 's', 'events': [{'role': 'assistant', 'event_id': 'reply1'}, {'role': 'assistant', 'event_id': 'other'}],
        'fingerprints': [photo['fingerprint'], 'a' * 64],
    })
    assert result.status_code == 200
    body = result.json()
    assert body['media']['assistant:reply1'][0]['photo_id'] == photo['id']
    assert 'assistant:other' not in body['media']
    assert body['photos'][photo['fingerprint']]['photo_id'] == photo['id']
    assert 'a' * 64 not in body['photos']
    assert 'base64' not in result.text and 'private-photo' not in result.text
    assert client.get('/api/gateway/album/photo/' + photo['id']).content == b'private-photo'
    assert client.post('/api/gateway/album/resolve', json={'session_tag': 's', 'events': [{'role': 'assistant', 'event_id': 'x'}] * 501}).status_code == 422


def test_session_detail_and_reply_recovery_carry_photo_only_reply(tmp_path):
    store = _store(tmp_path)
    session = store.get_or_create_session('s', 'shenyu-pwa')
    photo = store.save_album_photo(raw=b'p', note='自己写的')
    store.record_album_share('s', 'reply1', 'call1', photo['id'])
    store.append_message(session['id'], 'user', '发我看看')
    store.append_message(session['id'], 'assistant', '', source_table='reply_version', source_id='reply1')
    client = client_for(store)
    rows = client.get('/api/gateway/sessions/s').json()['recent_messages']
    assert rows[-1]['media'][0]['photo_id'] == photo['id']
    recovery = client.get('/api/gateway/sessions/s/reply-recovery').json()
    assert len(recovery['replies']) == 1
    assert recovery['replies'][0]['media'][0]['photo_id'] == photo['id']


import base64
import json
from functools import partial

import pytest

from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.request_logs import _record_upstream_payload
from shenyu_gateway.schemas import ChatRequest
from shenyu_gateway.sessions import SessionManager
from shenyu_gateway.tool_loop import run_internal_tool_loop, run_internal_tool_loop_stream, _execute_mixed_gateway_tool_calls
from shenyu_gateway.tool_registry import execute_gateway_tool
from shenyu_gateway.upstream_client import build_upstream_request, resolve_upstream
from tests.test_gateway_streaming import _nonstream_tool_loop_ctx


@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('action', ['send', 'open'])
async def test_album_real_registry_through_tool_loop_and_provider_payloads(tmp_path, protocol, stream, action):
    store = _store(tmp_path)
    session = store.get_or_create_session('s', 'shenyu-pwa')
    raw = b'private-pixels-for-upstream-only'
    encoded = base64.b64encode(raw).decode()
    photo = store.save_album_photo(raw=raw, mime='image/png', note='留给自己的话')
    cfg = RuntimeConfig()
    cfg.max_internal_tool_rounds = 3
    upstream = {**resolve_upstream(cfg), 'protocol': protocol}
    ctx = _nonstream_tool_loop_ctx([], max_rounds=3, assistant_outputs=[])
    ctx.cfg = cfg
    ctx.store = store
    ctx.body = ChatRequest(model='test-model', messages=[{'role':'user','content':'翻相册'}])
    ctx.request.headers = {}
    ctx.sessions = SessionManager(store, cfg)
    ctx.prepared_messages = [{'role':'user','content':'翻相册'}]
    ctx.meta = {'session': session, 'snapshot_messages': ctx.prepared_messages,
                'upstream': upstream,
                'reply_archive_event': {'id':'reply1','event_at':'2026-09-19T00:00:00Z'},
                'client_profile': {'emit_tool_events': True, 'emit_album_photos': True}}
    ctx.log_entry = {'reply_version_id':'reply1','request_payloads_retained': True}
    service = GatewayToolService(runtime_config=cfg, store=store, supabase=None)
    ctx.execute_gateway_tool = partial(execute_gateway_tool, service=service)
    ctx.build_upstream_request = partial(build_upstream_request, cfg=cfg)
    ctx.record_upstream_payload = _record_upstream_payload
    ctx.write_completion_context_snapshot = partial(write_completion_context_snapshot, store)
    args = {'tool':f'shenyu_album_{action}', 'params':{'photo_id':photo['id']}}
    call = {'index':0, 'id':'call1', 'type':'function', 'function':{'name':'shenyu_gateway_tool','arguments':json.dumps(args)}}
    payloads = []

    def capture(payload):
        payloads.append(payload)
        if len(payloads) == 2:
            assert (encoded in json.dumps(payload)) == (action == 'open')
            assert bool(store.message_media('s','reply1','assistant')) == (action == 'send')
            assert '_shenyu_tool_images' not in json.dumps(payload)

    async def call_json(request, url, payload, headers):
        capture(payload)
        first = len(payloads) == 1
        if protocol == 'anthropic':
            return {'id':'response','type':'message','role':'assistant', 'content':[
                {'type':'tool_use','id':'call1','name':'shenyu_gateway_tool','input':args}
            ] if first else [], 'stop_reason':'tool_use' if first else 'end_turn','usage':{}}
        return {'choices':[{'message':{'role':'assistant','content':'', **({'tool_calls':[call]} if first else {})}, 'finish_reason':'tool_calls' if first else 'stop'}], 'usage':{}}

    async def chunks(request, payload, headers, model, upstream):
        capture(payload)
        first = len(payloads) == 1
        yield {'choices':[{'index':0,'delta':{'tool_calls':[call]} if first else {'content':''}, 'finish_reason':'tool_calls' if first else 'stop'}]}

    ctx.call_upstream_json = call_json
    ctx.stream_upstream_openai_chunks = chunks
    if stream:
        wire = ''.join([chunk async for chunk in run_internal_tool_loop_stream(ctx)])
        assert 'data: [DONE]' in wire
    else:
        wire = json.dumps(await run_internal_tool_loop(ctx))
    assert len(payloads) == 2
    assert encoded not in wire
    assert ('"photo"' in wire) == (action == 'send')
    assert encoded not in json.dumps(ctx.log_entry)
    assert encoded not in json.dumps(store.get_recent_messages(session['id'], limit=20))
    snapshot = store.get_recent_context_snapshots(session['id'], 1)[0]['messages']
    assert encoded not in json.dumps(snapshot)
    if action == 'send':
        assert snapshot[-1]['media'][0]['photo_id'] == photo['id']
        assert snapshot[-1]['archive_event']['id'] == 'reply1'


@pytest.mark.asyncio
async def test_mixed_client_turn_retains_only_trusted_view_pointer(tmp_path):
    from shenyu_gateway.album_media import ALBUM_VIEW_KEY, TOOL_IMAGES_KEY
    store = _store(tmp_path)
    session = store.get_or_create_session('s', 'test-client')
    photo = store.save_album_photo(raw=b'never-serialize-me', note='原话')
    cfg = RuntimeConfig()
    ctx = _nonstream_tool_loop_ctx([], max_rounds=3, assistant_outputs=[])
    ctx.cfg, ctx.store, ctx.sessions = cfg, store, SessionManager(store, cfg)
    ctx.meta = {'session':session}
    ctx.execute_gateway_tool = partial(execute_gateway_tool, service=GatewayToolService(runtime_config=cfg, store=store, supabase=None))
    calls = [
        {'id':'open','type':'function','function':{'name':'shenyu_album_open','arguments':json.dumps({'photo_id':photo['id']})}},
        {'id':'client','type':'function','function':{'name':'read_file','arguments':'{}'}},
    ]
    completion = {'choices':[{'message':{'role':'assistant','content':'','tool_calls':calls}}]}
    await _execute_mixed_gateway_tool_calls(ctx, completion, calls)
    pending = store.find_pending_gateway_tool_turn(session['id'], ['client'])
    assert pending
    assert photo['id'] in json.dumps(pending)
    assert ALBUM_VIEW_KEY in json.dumps(pending)
    assert TOOL_IMAGES_KEY not in json.dumps(pending)
    assert 'base64' not in json.dumps(pending)


def test_photo_endpoint_never_serves_active_document_formats(tmp_path):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'<html>not a photo</html>', mime='text/html')
    response = client_for(store).get(f"/api/gateway/album/photo/{photo['id']}")
    assert response.status_code == 415
