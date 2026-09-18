"""Chat Recall must use the archive reader's source and visibility, not rollback data."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shenyu_gateway.archive_routes import ArchiveRouteDeps, build_archive_router
from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.local_chat_archive import LocalChatArchive, local_archive_for_config
from tests.fake_postgrest import project_select


class RollbackCloud:
    """A deliberately stale cloud original; returning it must fail SQLite tests."""
    def __init__(self):
        self.calls = []

    async def query(self, table, params):
        self.calls.append((table, params))
        return project_select([message('cloud-old', '海边：旧云端副本')], params)


def message(ident, content='海边：当前原文', event='2026-09-19T01:00:00Z', **extra):
    return dict(id=ident, session_tag='test', thread='test', client_name='shenyu-pwa',
                role='assistant', content=content, content_hash='hash-' + ident,
                event_at=event, archived_at=event, deleted_at=None, **extra)


@pytest.fixture
def archive_case(tmp_path):
    cfg = SimpleNamespace(chat_archive_backend='sqlite',
                          gateway_db_path=str(tmp_path / 'runtime.db'), chat_archive_db_path='')
    archive = LocalChatArchive(tmp_path / 'shenyu_chat_archive.db', create=True)
    cloud = RollbackCloud()
    service = GatewayToolService(runtime_config=cfg, supabase=cloud, store=None)
    return cfg, archive, cloud, service


@pytest.mark.parametrize('source', ['chat', 'conversation', 'archive', None])
def test_recall_uses_sqlite_for_explicit_chat_and_verbatim(archive_case, source):
    cfg, archive, cloud, service = archive_case
    original = message('local-new', '海边：' + '新原文' * 500)
    archive.append_rows([original])
    result = asyncio.run(service.recall('海边' if source else '海边原话', source_types=source))
    assert result['ok'] is True
    assert [item['source_id'] for item in result['items']] == ['local-new']
    item = result['items'][0]
    assert item['content'] == original['content']
    assert item['source_type'] == 'chat' and item['content_kind'] == 'assistant'
    assert item['event_date'] == original['event_at'] and item['has_more'] is False
    assert cloud.calls == []
    read = asyncio.run(service.recall_read(source or 'chat', 'local-new'))
    assert read['item'] == item
    assert cloud.calls == []


def test_local_recall_works_without_supabase(archive_case):
    cfg, archive, _, _ = archive_case
    archive.append_rows([message('local-only')])
    service = GatewayToolService(runtime_config=cfg, supabase=None, store=None)
    assert asyncio.run(service.recall('海边原话'))['items'][0]['source_id'] == 'local-only'
    assert asyncio.run(service.recall_read('chat', 'local-only'))['ok'] is True


def test_archive_api_and_recall_share_fold_and_delete_rules(archive_case):
    cfg, archive, cloud, service = archive_case
    archive.import_rows([message('first'), {**message('handoff'), 'content_hash': 'hash-first'}])
    archive.append_rows([message('new-version')])  # Equal words, genuinely distinct event.
    app = FastAPI()
    app.include_router(build_archive_router(ArchiveRouteDeps(
        get_supabase_client=lambda: cloud, get_local_archive=lambda: local_archive_for_config(cfg))))

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            visible = (await client.get('/api/archive/messages')).json()['messages']
            hits = (await client.get('/api/archive/search', params={'q': '海边'})).json()['results']
            recalled = await service.recall('海边原话')
            ids = {row['id'] for row in visible}
            assert ids == {'first', 'new-version'}
            assert ids == {row['id'] for row in hits}
            assert ids == {row['source_id'] for row in recalled['items']}
            assert not (await service.recall_read('chat', 'handoff'))['ok']
            response = await client.delete('/api/archive/messages/first')
            assert response.status_code == 200
            assert [row['source_id'] for row in (await service.recall('海边原话'))['items']] == ['new-version']
            for ident in ('first', 'handoff', 'cloud-old'):
                assert not (await service.recall_read('chat', ident))['ok']
    asyncio.run(exercise())
    assert cloud.calls == []
    assert archive.stats() == {'total': 3, 'active': 1, 'visible': 1}


@pytest.mark.parametrize('failure', ['missing', 'invalid', 'runtime-path'])
def test_unavailable_local_archive_fails_explicitly_without_cloud_fallback(archive_case, failure):
    cfg, archive, cloud, service = archive_case
    if failure == 'missing':
        archive.path.unlink()
    elif failure == 'invalid':
        cfg.chat_archive_db_path = str(archive.path.with_name('invalid.db'))
        Path(cfg.chat_archive_db_path).write_bytes(b'not a database')
    else:
        cfg.chat_archive_db_path = cfg.gateway_db_path
    result = asyncio.run(service.recall('海边原话'))
    read = asyncio.run(service.recall_read('chat', 'cloud-old'))
    assert result['ok'] is False and result['items'] == []
    assert 'unavailable' in result['error'].lower()
    assert read['ok'] is False and 'unavailable' in read['error'].lower()
    assert cloud.calls == []
    assert not Path(cfg.gateway_db_path).exists()
    if failure == 'missing':
        assert not archive.path.exists()  # No blank replacement archive created.


def test_supabase_mode_remains_supported_without_local_file(archive_case):
    cfg, archive, cloud, service = archive_case
    cfg.chat_archive_backend = 'supabase'
    archive.path.unlink()
    result = asyncio.run(service.recall('海边原话'))
    assert result['items'][0]['source_id'] == 'cloud-old'
    assert asyncio.run(service.recall_read('chat', 'cloud-old'))['ok'] is True
    assert len(cloud.calls) == 2


def test_non_chat_recall_does_not_open_archive_or_replace_memory_sources(archive_case, monkeypatch):
    cfg, archive, cloud, service = archive_case
    archive.path.unlink()
    calls = []
    class Index:
        async def recall(self, **kwargs):
            calls.append(kwargs)
            return {'ok': True, 'items': [{'source_type': 'journal', 'source_id': 'diary', 'content': '日记'}]}
    monkeypatch.setattr(service, '_recall_index', lambda: Index())
    result = asyncio.run(service.recall('日记', source_types=['journal'], mode='broad'))
    assert result['items'][0]['source_id'] == 'diary'
    assert calls[0]['source_types'] == ['journal']
    assert cloud.calls == []


def test_local_io_runs_off_the_event_loop(archive_case, monkeypatch):
    _, archive, _, service = archive_case
    archive.append_rows([message('local')])
    from shenyu_gateway.gateway_tools import _recall
    original = local_archive_for_config
    loop_thread = threading.get_ident()
    worker_threads = []
    def checked(cfg):
        worker_threads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread
        return original(cfg)
    monkeypatch.setattr(_recall, 'local_archive_for_config', checked, raising=False)
    assert asyncio.run(service.recall('海边原话'))['ok']
    assert asyncio.run(service.recall_read('chat', 'local'))['ok']
    assert len(worker_threads) == 2


@pytest.mark.parametrize('terms', [['海边', '山顶'], ['100%', 'a_b', 'x*y'], ['É', 'K', 'ſ', 'İ']])
def test_recall_candidates_match_visible_literal_search_union(archive_case, terms):
    _, archive, _, _ = archive_case
    texts = ['海边散步', '山顶看云', '100%', 'a_b', 'x*y', '1000', 'axb', 'xay', 'é', 'k', 's', 'i', '无关']
    archive.append_rows([message(str(i), text) for i, text in enumerate(texts)])
    expected = {r['id'] for term in terms for r in archive.search(term)['results']}
    rows = archive.recall_candidates(terms)
    assert {row['id'] for row in rows} == expected
    assert all('content' in row for row in rows)


def test_candidate_filter_precedes_limit_and_retains_recency_ties(archive_case):
    _, archive, _, service = archive_case
    archive.append_rows([message('old-hit', '海边')])
    archive.append_rows([message(f'noise-{i:03d}', '无关', event='2026-09-19T02:00:00Z') for i in range(250)])
    assert asyncio.run(service.recall('海边原话'))['items'][0]['source_id'] == 'old-hit'
    rows = archive.recall_candidates([], limit=3)
    assert [r['id'] for r in rows] == ['noise-249', 'noise-248', 'noise-247']


@pytest.mark.parametrize('broker', [False, True])
def test_public_tool_dispatch_reaches_the_same_local_original(archive_case, broker):
    from shenyu_gateway.config import RuntimeConfig
    from shenyu_gateway.tool_registry import execute_gateway_tool
    cfg, archive, cloud, service = archive_case
    runtime_cfg = RuntimeConfig()
    for key, value in vars(cfg).items():
        setattr(runtime_cfg, key, value)
    cfg = runtime_cfg
    cfg.enable_gateway_tools = True
    cfg.gateway_tool_surface = "full"
    service.cfg = cfg
    archive.append_rows([message('through-tool')])

    async def invoke(name, arguments):
        if broker:
            name, arguments = 'shenyu_gateway_tool', {'tool': name, 'params': arguments}
        return await execute_gateway_tool(name, arguments, session_tag='test', cfg=cfg, service=service)

    result = asyncio.run(invoke('shenyu_recall', {'query': '海边', 'source_types': ['chat']}))
    assert result.get('ok'), result
    assert result['items'][0]['source_id'] == 'through-tool'
    read = asyncio.run(invoke('shenyu_recall_read', {'source_type': 'chat', 'source_id': 'through-tool'}))
    assert read['item']['content'] == '海边：当前原文'
    assert cloud.calls == []
