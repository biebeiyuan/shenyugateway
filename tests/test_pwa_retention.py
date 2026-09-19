"""Owner-facing conversation organization must not erase resident records."""
from types import SimpleNamespace
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router
from shenyu_gateway.store import GatewayStore


def make_app(store):
    deps = GatewayAdminRouteDeps(
        cfg=SimpleNamespace(gateway_message_retention=2000),
        get_supabase_client=lambda: None,
        get_session_store=lambda: store,
        require_session_store=lambda: store,
        context_builder=lambda *args: None,
        resolve_upstream=lambda: {},
        prune_runtime_state=lambda *args: {},
        cold_start_idle_minutes=lambda *args: 0,
        now=lambda: datetime.now(timezone.utc),
        request_logs=[],
    )
    app = FastAPI()
    app.include_router(build_gateway_admin_router(deps))
    return app


def seed(store):
    first = store.get_or_create_session('keep-a', 'shenyu-pwa')
    second = store.get_or_create_session('keep-b', 'another-client')
    for session in (first, second):
        store.append_message(session['id'], 'user', '原话')
        store.append_message(session['id'], 'tool', '{"ok":true}', tool_name='shenyu_recall')
        store.append_heartbeat(session['id'], '不可随列表整理删除的心跳')
        with store._connect() as conn:
            conn.execute(
                'INSERT INTO request_context_snapshots '
                '(id,session_id,session_tag,messages_json,created_at) VALUES (?,?,?,?,?)',
                ('snap-' + session['id'], session['id'], session['session_tag'], '[]', session['started_at']),
            )
    return first, second


def retained_rows(store):
    with store._connect() as conn:
        return {table: [dict(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                for table in ('gateway_messages', 'heartbeat_entries', 'request_context_snapshots',
                              'context_window_states', 'cold_start_snapshots', 'album_photos',
                              'album_message_media', 'pending_gateway_tool_turns')}


@pytest.mark.asyncio
async def test_old_delete_endpoint_refuses_without_removing_any_records(tmp_path):
    store = GatewayStore(str(tmp_path / 'runtime.db'))
    first, _ = seed(store)
    before = retained_rows(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(store)), base_url='http://test') as client:
        response = await client.request('DELETE', '/api/gateway/sessions/keep-a',
                                        json={'confirm': 'keep-a'}, headers={'X-Shenyu-Client': 'shenyu-pwa'})
    assert response.status_code == 409
    assert '收起' in response.json()['detail']
    assert retained_rows(store) == before
    assert store.get_session_by_tag('keep-a')['id'] == first['id']


@pytest.mark.asyncio
async def test_hiding_and_restoring_only_changes_list_visibility(tmp_path):
    store = GatewayStore(str(tmp_path / 'runtime.db'))
    first, _ = seed(store)
    before = retained_rows(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(store)), base_url='http://test') as client:
        response = await client.patch('/api/gateway/sessions/keep-a/visibility', json={'hidden': True})
        assert response.status_code == 200
        assert response.json()['session']['hidden_at']
        visible = (await client.get('/api/gateway/sessions', params={'visibility': 'visible'})).json()['sessions']
        hidden = (await client.get('/api/gateway/sessions', params={'visibility': 'hidden'})).json()['sessions']
        assert [s['session_tag'] for s in visible] == ['keep-b']
        assert [s['session_tag'] for s in hidden] == ['keep-a']
        # Existing internal callers retain the full set: no cold-start behavior change.
        assert len(store.list_sessions()) == 2
        assert retained_rows(store) == before
        assert store.get_session_by_tag('keep-a')['last_active_at'] == first['last_active_at']
        response = await client.patch('/api/gateway/sessions/keep-a/visibility', json={'hidden': False})
        assert response.status_code == 200
        assert not response.json()['session']['hidden_at']
        assert retained_rows(store) == before
        assert len((await client.get('/api/gateway/sessions', params={'visibility': 'visible'})).json()['sessions']) == 2


@pytest.mark.asyncio
async def test_visibility_requires_a_real_boolean(tmp_path):
    store = GatewayStore(str(tmp_path / 'runtime.db'))
    seed(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(store)), base_url='http://test') as client:
        response = await client.patch('/api/gateway/sessions/keep-a/visibility', json={'hidden': 'false'})
        assert response.status_code == 422
        assert len(store.list_sessions()) == 2
