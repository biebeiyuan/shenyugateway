"""Archive identity is independent from the model/display projection."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib

import pytest

from shenyu_gateway.chat_archive import ChatArchiveService
from shenyu_gateway.local_chat_archive import LocalChatArchive
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.schemas import ChatRequest


def setup_archive(tmp_path):
    archive = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store = GatewayStore(str(tmp_path / 'runtime.db'))
    cfg = SimpleNamespace(enable_chat_archive=True, chat_archive_backend='sqlite',
        chat_archive_db_path=str(archive.path), gateway_db_path=str(store.db_path),
        chat_archive_seen_retention=10000)
    return archive, store, ChatArchiveService(store, None, cfg)


def message(ident, text, role='assistant', time='2026-09-18T08:00:00+00:00'):
    return {'role': role, 'content': text, 'archive_event': {'id': ident, 'event_at': time}}


@pytest.mark.asyncio
@pytest.mark.parametrize('wrapped', [
    '[回响]private[/回响]\n\nVisible body',
    '<heartbeat>private</heartbeat>\n\nVisible body',
    '[回响]private[/回响]\n\nVisible body<heartbeat>private</heartbeat>',
])
async def test_legacy_wrapped_and_visible_forms_are_one_message(tmp_path, wrapped):
    archive, _, service = setup_archive(tmp_path)
    window = [{'role': 'assistant', 'content': wrapped}]
    before = deepcopy(window)
    first = await service.archive_window(session_tag='old', client_name='pwa', messages=window)
    second = await service.archive_window(session_tag='new', client_name='pwa',
        messages=[{'role': 'assistant', 'content': 'Visible body'}])
    assert first['archived'] == 1
    assert second['archived'] == 0
    assert [row['content'] for row in archive.list_messages()] == ['Visible body']
    assert window == before


@pytest.mark.asyncio
async def test_legacy_hash_migration_does_not_rearchive_or_rewrite_original(tmp_path):
    archive, store, service = setup_archive(tmp_path)
    original = '\n\nVisible body'
    digest = hashlib.sha256(f'assistant\n{original}'.encode()).hexdigest()
    archive.import_rows([dict(id='old-original', role='assistant', content=original,
        content_hash=digest, event_at='2026-09-11T12:00:00Z', archived_at='2026-09-11T12:01:00Z')])
    store.mark_archive_hashes_seen('old', [digest])
    before = archive.export_rows()
    result = await service.archive_window(session_tag='new', client_name='pwa',
        messages=[{'role': 'assistant', 'content': 'Visible body'}])
    assert result['archived'] == 0
    assert archive.export_rows() == before


@pytest.mark.asyncio
async def test_identified_repeated_words_are_distinct_and_keep_original_times(tmp_path):
    archive, _, service = setup_archive(tmp_path)
    rows = [message('u1', '好的', 'user'), message('a1', '收到'),
            message('u2', '好的', 'user', '2026-09-18T10:00:00Z'),
            message('a2', '收到', time='2026-09-18T10:00:01Z')]
    result = await service.archive_window(session_tag='pwa', client_name='pwa', messages=rows)
    assert result['archived'] == 4
    visible = archive.list_messages()
    assert [row['role'] for row in visible] == ['user', 'assistant', 'user', 'assistant']
    assert visible[0]['event_at'] == '2026-09-18T08:00:00+00:00'
    assert visible[-1]['event_at'] == '2026-09-18T10:00:01+00:00'


@pytest.mark.asyncio
async def test_identified_replay_survives_projection_change_cache_loss_and_delete(tmp_path):
    archive, store, service = setup_archive(tmp_path)
    old = message('stable-reply', '[回响]private[/回响]\n\nVisible body')
    assert (await service.archive_window(session_tag='old', client_name='pwa', messages=[old]))['archived'] == 1
    original = archive.export_rows()
    with store._connect() as conn:
        conn.execute('DELETE FROM chat_archive_seen')
    # A future display projection is not allowed to create a new event ID.
    changed = message('stable-reply', 'Visible body with a different display projection')
    assert (await service.archive_window(session_tag='new', client_name='pwa', messages=[changed]))['archived'] == 0
    assert archive.export_rows() == original
    archive.soft_delete(original[0]['id'])
    assert (await service.archive_window(session_tag='new', client_name='pwa', messages=[old]))['archived'] == 0
    assert archive.stats()['total'] == 1
    assert archive.stats()['active'] == 0


@pytest.mark.asyncio
async def test_same_slot_new_revision_is_a_distinct_event(tmp_path):
    archive, _, service = setup_archive(tmp_path)
    for ident, text in [('u-v1', '初稿'), ('u-v2', '改稿')]:
        await service.archive_window(session_tag='pwa', client_name='pwa',
            messages=[message(ident, text, 'user')])
    assert [r['content'] for r in archive.list_messages()] == ['初稿', '改稿']


@pytest.mark.asyncio
async def test_private_only_response_does_not_become_archive_text(tmp_path):
    archive, _, service = setup_archive(tmp_path)
    result = await service.archive_window(session_tag='pwa', client_name='pwa',
        messages=[message('private', '[回响]private[/回响]\n<heartbeat>secret</heartbeat>')])
    assert result['archived'] == 0
    assert archive.stats()['total'] == 0


def test_message_schema_preserves_optional_archive_identity():
    msg = message('stable-id', 'body')
    parsed = ChatRequest(model='test', messages=[msg])
    assert parsed.messages[0].model_dump(exclude_none=True) == msg


@pytest.mark.asyncio
async def test_pending_reply_does_not_freeze_partial_content(tmp_path):
    archive, _, service = setup_archive(tmp_path)
    partial = {**message('recoverable', 'half'), 'archive_pending': True}
    assert (await service.archive_window(session_tag='pwa', client_name='pwa', messages=[partial]))['archived'] == 0
    assert archive.stats()['total'] == 0
    full = message('recoverable', 'half then the recovered remainder')
    assert (await service.archive_window(session_tag='pwa', client_name='pwa', messages=[full]))['archived'] == 1
    assert archive.list_messages()[0]['content'] == full['content']


def test_projection_is_idempotent_when_private_blocks_change_order():
    from shenyu_gateway.chat_archive import archive_visible_text
    raw = '<heartbeat>private</heartbeat>\n[回响]echo[/回响]\n\nbody\n\n  interior'
    visible = archive_visible_text('assistant', raw)
    assert visible == 'body\n\n  interior'
    assert archive_visible_text('assistant', visible) == visible
    # User quotes are user text, not private generated blocks.
    assert archive_visible_text('user', raw) == raw


def test_recovery_does_not_upgrade_legacy_source_ids_to_new_archive_events():
    from shenyu_gateway.gateway_admin_routes import collect_reply_recovery_rows
    rows = [{'role': 'user', 'content': 'question'},
            {'role': 'assistant', 'content': 'answer', 'source_id': 'old-roll',
             'created_at': '2026-08-01T12:00:00Z'}]
    assert 'archive_event' not in collect_reply_recovery_rows(rows)['replies'][0]


@pytest.mark.asyncio
async def test_legacy_aliases_do_not_multiply_seen_cache_capacity(tmp_path):
    _, store, service = setup_archive(tmp_path)
    await service.archive_window(session_tag='pwa', client_name='pwa',
        messages=[{'role': 'assistant', 'content': '[回响]echo[/回响]\n\nbody'}])
    with store._connect() as conn:
        assert conn.execute('SELECT count(*) FROM chat_archive_seen').fetchone()[0] == 1


def test_recovery_only_carries_matching_recorded_envelope():
    from shenyu_gateway.gateway_admin_routes import collect_reply_recovery_rows
    rows = [{'role': 'user', 'content': 'question'},
            {'role': 'assistant', 'content': 'answer', 'source_id': 'new-roll'}]
    source = message('new-roll', 'answer')
    result = collect_reply_recovery_rows(rows, [{'messages': [source]}])
    assert result['replies'][0]['archive_event'] == source['archive_event']
    result = collect_reply_recovery_rows(rows, [{'messages': [message('unrelated', 'answer')]}])
    assert 'archive_event' not in result['replies'][0]


@pytest.mark.asyncio
async def test_identified_concurrent_writes_and_strict_import(tmp_path):
    import asyncio
    archive, _, service = setup_archive(tmp_path)
    async def capture():
        return await service.archive_window(session_tag='pwa', client_name='pwa',
            messages=[message('one', 'body')])
    results = await asyncio.gather(capture(), capture())
    assert sum(result['archived'] for result in results) == 1
    original = archive.export_rows()[0]
    with pytest.raises(ValueError, match='original conflict'):
        archive.import_rows([{**original, 'content': 'cannot rewrite through import'}])
    assert archive.export_rows() == [original]


@pytest.mark.asyncio
async def test_cloud_capture_uses_ignore_duplicates_not_merge(tmp_path):
    import json
    import httpx
    from shenyu_gateway.supabase import SupabaseClient
    archive, store, service = setup_archive(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers['Prefer'] == 'resolution=ignore-duplicates,return=representation'
        assert dict(request.url.params) == {'on_conflict': 'id', 'select': 'id'}
        payload = json.loads(request.content)
        assert payload[0]['content'] == 'body'
        assert payload[0]['content_hash'].startswith('event:v1:')
        return httpx.Response(201, json=[{'id': payload[0]['id']}] if len(calls) == 1 else [])
    cloud = SupabaseClient('https://archive.example.invalid', 'test-only')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cloud._client = client
        cfg = SimpleNamespace(**vars(service.cfg))
        cfg.chat_archive_backend = 'supabase'
        service = ChatArchiveService(store, cloud, cfg)
        for expected in (1, 0):
            result = await service.archive_window(session_tag='pwa', client_name='pwa',
                messages=[message('cloud-one', 'body')])
            assert result['archived'] == expected
    assert len(calls) == 2
    assert archive.stats()['total'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('room', [False, True])
async def test_preparation_keeps_envelopes_only_in_archive_and_snapshots(tmp_path, monkeypatch, room):
    import asyncio
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from shenyu_gateway import prepare_messages as preparation
    from shenyu_gateway.context_snapshots import write_completion_context_snapshot
    from tests.test_gateway_context import _context_builder
    archive, store, service = setup_archive(tmp_path)
    builder = _context_builder(store)
    monkeypatch.setattr(preparation._mcp_registry, 'ensure_fresh', AsyncMock())
    async def normal_package(session, **kwargs):
        return {'stable_charter': 'fixed', 'heartbeat_digest': '',
                'heartbeat_pending_ids': [], 'calendar_context': {}}
    async def room_package(session, **kwargs):
        return {'layers': {'stable': 'room'}}
    monkeypatch.setattr(builder, 'build_context_package', normal_package)
    monkeypatch.setattr(builder, 'build_room_context_package', room_package)
    cfg = service.cfg
    cfg.max_client_messages = 40
    cfg.epoch_reset_on_cold_cache = False
    cfg.enable_room_mode = True
    cfg.client_tool_surface = 'none'
    cfg.anthropic_cache_ttl = '1h'
    cfg.openai_cache_ttl = '5m'
    history = [{**message('u1', 'question', 'user'), 'archive_replay': True},
               {**message('a1', 'half'), 'archive_pending': True},
               message('u2', '【窗边 · 18/09 18:00】' if room else 'next question', 'user')]
    deps = preparation.PrepareMessagesDeps(cfg=cfg, store=store, supabase_client=None,
        context_builder_factory=lambda *args: builder, client_name_from_request=lambda request: 'shenyu-pwa',
        session_tag_from_request=lambda *args, **kwargs: 'window', resolve_upstream=lambda: {'protocol': 'anthropic'},
        maybe_prepare_cold_start_snapshot=lambda *args: None, prune_runtime_state=lambda *args: {})
    reply_event = message('a2', '')['archive_event']
    body = ChatRequest(model='test', messages=history,
        metadata={'reply_version_id': 'a2', 'reply_archive_event': reply_event})
    prepared, meta = await preparation.prepare_messages(Request({'type': 'http', 'headers': []}), body, deps)
    await asyncio.gather(*tuple(preparation._BACKGROUND_TASKS))
    assert all('archive_event' not in row and 'archive_pending' not in row and 'archive_replay' not in row for row in prepared)
    assert meta['snapshot_messages'][0]['archive_replay'] is True
    assert meta['snapshot_messages'][0]['archive_event'] == history[0]['archive_event']
    assert meta['snapshot_messages'][1]['archive_pending'] is True
    assert meta['reply_archive_event'] == reply_event
    assert [row['role'] for row in archive.list_messages()] == ['user', 'user']
    snapshot = write_completion_context_snapshot(store, meta, 'complete', echo='private')
    assert snapshot['messages'][-1]['archive_event'] == reply_event
    assert body.messages[1].archive_pending is True


@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
async def test_direct_provider_builder_never_leaks_archive_metadata(protocol):
    import json
    from shenyu_gateway.config import RuntimeConfig
    from shenyu_gateway.upstream_client import build_upstream_request
    cfg = RuntimeConfig()
    cfg.upstream_url = 'https://upstream.example.invalid'
    cfg.upstream_protocol = protocol
    cfg.enable_gateway_tools = False
    cfg.enable_mcp_tools = False
    body = ChatRequest(model='test', messages=[{**message('u1', 'body', 'user'), 'archive_pending': True, 'archive_replay': True}],
        metadata={'reply_archive_event': message('reply', '')['archive_event']})
    payload, *_ = await build_upstream_request(None, body, cfg=cfg)
    rendered = json.dumps(payload)
    assert 'archive_event' not in rendered and 'archive_pending' not in rendered and 'archive_replay' not in rendered
    assert body.messages[0].archive_replay is True
    assert body.messages[0].archive_event['id'] == 'u1'


def test_legacy_backfill_shares_projection_and_rejects_identified_windows():
    from scripts.backfill_chat_archive import _candidate_rows
    kwargs = dict(tag='old', client_name='pwa', created_at='2026-08-01T08:00:00Z', existing=set())
    rows = _candidate_rows(messages=[{'role': 'assistant', 'content':
        '[回响]private[/回响]\n\nbody<heartbeat>secret</heartbeat>'}], **kwargs)
    assert rows[0]['content'] == 'body'
    with pytest.raises(ValueError, match='[Ll]egacy'):
        _candidate_rows(messages=[message('modern', 'body')], **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['user', 'assistant'])
@pytest.mark.parametrize('deleted', [False, True])
async def test_restored_history_without_identity_cannot_rearchive_after_cache_loss(tmp_path, role, deleted):
    archive, store, service = setup_archive(tmp_path)
    original = message('stable-' + role, 'An original with unchanged text', role)
    await service.archive_window(session_tag='old', client_name='pwa', messages=[original])
    if deleted:
        archive.soft_delete(archive.export_rows()[0]['id'])
    before = archive.export_rows()
    with store._connect() as conn:
        conn.execute('DELETE FROM chat_archive_seen')
    # A raw inspection-stream restore lost its source envelope, but keeps its
    # replay provenance. It may still be model context; it is not a new send.
    wire = {'role': role, 'content': original['content'], 'archive_replay': True}
    parsed = ChatRequest(model='test', messages=[wire]).messages[0].model_dump(exclude_none=True)
    assert (await service.archive_window(session_tag='reopened', client_name='pwa', messages=[parsed]))['archived'] == 0
    assert archive.export_rows() == before


@pytest.mark.asyncio
async def test_restored_complete_identity_can_still_capture_unarchived_selected_reply(tmp_path):
    archive, _, service = setup_archive(tmp_path)
    reply = {**message('completed', 'Complete recovered reply'), 'archive_replay': True}
    assert (await service.archive_window(session_tag='pwa', client_name='pwa', messages=[reply]))['archived'] == 1
    assert (await service.archive_window(session_tag='pwa', client_name='pwa', messages=[reply]))['archived'] == 0
    assert archive.list_messages()[0]['content'] == reply['content']


@pytest.mark.asyncio
async def test_unknown_replay_neither_consumes_legacy_cache_nor_blocks_new_sends(tmp_path):
    archive, _, service = setup_archive(tmp_path)
    text = 'same visible words'
    replay = {'role': 'user', 'content': text, 'archive_replay': True}
    assert (await service.archive_window(session_tag='pwa', client_name='pwa', messages=[replay]))['archived'] == 0
    assert (await service.archive_window(session_tag='old-client', client_name='old',
        messages=[{'role': 'user', 'content': text}]))['archived'] == 1
    assert (await service.archive_window(session_tag='pwa', client_name='pwa',
        messages=[message('real-new-send', text, 'user')]))['archived'] == 1
    assert len(archive.list_messages()) == 2


def test_legacy_backfill_refuses_unidentified_restoration_sources():
    from scripts.backfill_chat_archive import _candidate_rows
    with pytest.raises(ValueError, match='[Ll]egacy'):
        _candidate_rows(tag='old', client_name='pwa', created_at='2026-08-01T08:00:00Z', existing=set(),
            messages=[{'role': 'assistant', 'content': 'restored body', 'archive_replay': True}])


@pytest.mark.asyncio
async def test_replay_guard_applies_to_cloud_capture_too(tmp_path):
    _, store, local = setup_archive(tmp_path)
    class NoCloudWrite:
        async def insert_many(self, *args, **kwargs):
            pytest.fail('unidentified replay must not write legacy cloud rows')
        async def insert_archive_events(self, *args, **kwargs):
            pytest.fail('unidentified replay has no immutable event to write')
    cfg = SimpleNamespace(**vars(local.cfg))
    cfg.chat_archive_backend = 'supabase'
    service = ChatArchiveService(store, NoCloudWrite(), cfg)
    result = await service.archive_window(session_tag='old', client_name='pwa',
        messages=[{'role': 'assistant', 'content': 'old body', 'archive_replay': True}])
    assert result['archived'] == 0


def test_completion_snapshot_reaches_real_recovery_api_without_client_resend(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from shenyu_gateway.context_snapshots import write_completion_context_snapshot
    from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router
    from shenyu_gateway.sessions import SessionManager
    archive, store, service = setup_archive(tmp_path)
    cfg = service.cfg
    cfg.gateway_message_retention = 1500
    sessions = SessionManager(store, cfg)
    session = sessions.open_session('contract-test', 'shenyu-pwa')
    user = message('user-contract', 'synthetic question', 'user')
    event = message('reply-contract', '')['archive_event']
    sessions.log_input_messages(session['id'], [user])
    sessions.log_assistant_output(session['id'], {'role': 'assistant', 'content': 'synthetic complete reply'},
        reply_version_id=event['id'])
    write_completion_context_snapshot(store,
        {'session': session, 'snapshot_messages': [user], 'reply_archive_event': event},
        'synthetic complete reply')
    app = FastAPI()
    app.include_router(build_gateway_admin_router(GatewayAdminRouteDeps(
        cfg=cfg, get_supabase_client=lambda: None, get_session_store=lambda: store,
        require_session_store=lambda: store, context_builder=lambda *a, **k: None,
        resolve_upstream=lambda: {}, prune_runtime_state=lambda **k: {},
        cold_start_idle_minutes=lambda s: 0, now=lambda: None, request_logs=[])))
    with TestClient(app) as client:
        detail = client.get('/api/gateway/sessions/contract-test')
        recovery = client.get('/api/gateway/sessions/contract-test/reply-recovery')
    assert detail.status_code == recovery.status_code == 200
    assert detail.json()['context_snapshots'][0]['messages'][-1]['archive_event'] == event
    assert all('archive_event' not in row for row in detail.json()['recent_messages'])
    assert recovery.json()['replies'][0]['archive_event'] == event
    # A completed recovery snapshot is not itself formal archive acceptance.
    assert archive.stats()['total'] == 0


@pytest.mark.asyncio
async def test_unidentified_replay_reports_count_without_logging_original(tmp_path, caplog):
    from shenyu_gateway.chat_archive import archive_window_safely
    archive, _, service = setup_archive(tmp_path)
    content = 'Private restored text must never appear in operational logs'
    window = [{'role': 'assistant', 'content': content, 'archive_replay': True}]
    with caplog.at_level('INFO'):
        await archive_window_safely(service, session_tag='reopened', client_name='pwa', messages=window)
    assert 'deferred_replays=1' in caplog.text
    assert 'missing_archive_identity' in caplog.text
    assert content not in caplog.text
    assert archive.stats()['total'] == 0
