from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from shenyu_gateway.archive_routes import ArchiveRouteDeps, build_archive_router
from shenyu_gateway.chat_archive import ChatArchiveService
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.local_chat_archive import LocalChatArchive, local_archive_for_config
from shenyu_gateway.store import GatewayStore
from .test_local_chat_archive import row


def test_local_archive_config_is_deployment_only_and_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv('CHAT_ARCHIVE_BACKEND', raising=False)
    monkeypatch.delenv('CHAT_ARCHIVE_DB_PATH', raising=False)
    cfg = RuntimeConfig()
    assert getattr(cfg, 'chat_archive_backend', None) == 'supabase'
    assert local_archive_for_config(cfg) is None
    monkeypatch.setenv('CHAT_ARCHIVE_BACKEND','sqlite')
    monkeypatch.setenv('CHAT_ARCHIVE_DB_PATH',str(tmp_path/'archive.db'))
    cfg = RuntimeConfig()
    with pytest.raises(FileNotFoundError): local_archive_for_config(cfg)
    LocalChatArchive(tmp_path/'archive.db',create=True)
    assert local_archive_for_config(cfg).path == tmp_path/'archive.db'
    monkeypatch.setenv('CHAT_ARCHIVE_BACKEND','typo')
    with pytest.raises(ValueError,match='CHAT_ARCHIVE_BACKEND'): RuntimeConfig()


@pytest.mark.asyncio
async def test_existing_archiver_can_write_locally_without_supabase(tmp_path):
    local = LocalChatArchive(tmp_path/'archive.db',create=True)
    runtime = GatewayStore(str(tmp_path/'runtime.db'))
    cfg=SimpleNamespace(enable_chat_archive=True,chat_archive_backend='sqlite',
                        chat_archive_db_path=str(local.path),gateway_db_path=str(runtime.db_path),
                        chat_archive_seen_retention=10000)
    service=ChatArchiveService(runtime,None,cfg)
    assert service.enabled(), 'sqlite archive must not depend on a Supabase client'
    messages=[{'role':'user','content':'你好'}, {'role':'assistant','content':'[回响]私密回响[/回响]你也好'},
              {'role':'tool','content':'not original dialogue'}]
    import copy
    before=copy.deepcopy(messages)
    result=await service.archive_window(session_tag='7.18',client_name='shenyu-pwa',messages=messages)
    assert result['archived']==2
    assert [r['content'] for r in local.list_messages()]==['你好','你也好']
    assert messages==before
    again=await service.archive_window(session_tag='7.18',client_name='shenyu-pwa',messages=messages)
    assert again['archived']==0


@pytest.mark.asyncio
async def test_local_archive_api_keeps_contract_and_never_queries_supabase(tmp_path):
    assert 'get_local_archive' in {f.name for f in fields(ArchiveRouteDeps)}, 'router lacks a local archive dependency'
    local=LocalChatArchive(tmp_path/'archive.db',create=True)
    local.append_rows([row('a','你好沈予'),row('b','你好沈予',session='B')])
    def cloud():
        raise AssertionError('archive route must not read cloud when local is selected')
    app=FastAPI()
    app.include_router(build_archive_router(ArchiveRouteDeps(get_supabase_client=cloud,get_local_archive=lambda:local)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/api/archive/days',params={'month':'2026-09'})
        assert result.json()=={'days':[{'date':'2026-09-17','count':2}]}
        result=await client.get('/api/archive/messages',params={'limit':1})
        assert result.status_code==200 and result.json()['count']==1
        assert result.json()['messages'][0]['id']=='b'
        result=await client.get('/api/archive/search',params={'q':'沈予','limit':1})
        assert result.status_code==200 and result.json()['has_more'] is True
        assert result.json()['results'][0]['snippet_match']=='沈予'
        cursor=result.json()['next_cursor']
        result=await client.get('/api/archive/search',params={'q':'沈予','limit':1,'cursor':cursor})
        assert result.json()['results'][0]['id']=='a' and result.json()['has_more'] is False
        assert (await client.get('/api/archive/messages',params={'before':'bad'})).status_code==400
        assert (await client.delete('/api/archive/messages/a')).json()=={'ok':True,'deleted':1}
        assert (await client.get('/api/archive/messages')).json()['count']==1


@pytest.mark.asyncio
async def test_origin_book_calls_still_use_supabase_when_archive_is_local(tmp_path):
    assert 'get_local_archive' in {f.name for f in fields(ArchiveRouteDeps)}
    from .test_conflict_and_archive import FakeSupabase
    cloud=FakeSupabase()
    local=LocalChatArchive(tmp_path/'archive.db',create=True)
    app=FastAPI()
    app.include_router(build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda:cloud,get_local_archive=lambda:local)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.post('/api/conflict-books',json={'title':'原文书','original_text':'不能改','message_refs':['old-id']})
        assert result.status_code==200
    assert cloud.tables['shenyu_conflict_books'][0]['original_text']=='不能改'
    assert local.stats()['total']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('history_count',[9,81])
async def test_archive_destination_does_not_change_prepared_context(tmp_path,monkeypatch,history_count):
    """Run the real preparation/window/layer code; only external memory is fixed."""
    import asyncio
    import copy
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from shenyu_gateway import prepare_messages as preparation
    from shenyu_gateway.schemas import ChatRequest
    from tests.test_gateway_context import _context_builder
    from .test_conflict_and_archive import FakeSupabase

    monkeypatch.setattr(preparation._mcp_registry,'ensure_fresh',AsyncMock())
    history=[{'role':'user' if i%2==0 else 'assistant','content':f'原话 {i}'} for i in range(history_count)]
    original=copy.deepcopy(history)
    outcomes=[]
    for backend in ('supabase','sqlite'):
        runtime=GatewayStore(str(tmp_path/f'{backend}-runtime.db'))
        local=LocalChatArchive(tmp_path/f'{backend}-archive.db',create=True)
        builder=_context_builder(runtime)
        async def package(session,**kwargs):
            return {'stable_charter':'不变的宪章','heartbeat_digest':'不变的心跳',
                    'heartbeat_pending_ids':[],'calendar_context':{}}
        monkeypatch.setattr(builder,'build_context_package',package)
        cfg=SimpleNamespace(max_client_messages=40,epoch_reset_on_cold_cache=False,
            enable_room_mode=False,client_tool_surface='none',anthropic_cache_ttl='1h',openai_cache_ttl='5m',
            enable_chat_archive=True,chat_archive_backend=backend,chat_archive_db_path=str(local.path),
            gateway_db_path=str(runtime.db_path),chat_archive_seen_retention=10000)
        deps=preparation.PrepareMessagesDeps(cfg=cfg,store=runtime,supabase_client=FakeSupabase(),
            context_builder_factory=lambda *args:builder,client_name_from_request=lambda request:'shenyu-pwa',
            session_tag_from_request=lambda *args,**kwargs:'same-window',resolve_upstream=lambda:{'protocol':'anthropic'},
            maybe_prepare_cold_start_snapshot=lambda *args:None,prune_runtime_state=lambda *args:{})
        messages,meta=await preparation.prepare_messages(
            Request({'type':'http','headers':[]}),ChatRequest(model='test',messages=history),deps)
        # Await the existing archive side task; do not merely assert before it ran.
        await asyncio.gather(*tuple(preparation._BACKGROUND_TASKS))
        outcomes.append((messages,meta['snapshot_messages'],meta['cache_layers'],meta['context_event']))
    assert history==original
    assert outcomes[0]==outcomes[1]


@pytest.mark.asyncio
async def test_archive_unavailable_after_startup_does_not_break_chat_preparation(tmp_path, caplog):
    from shenyu_gateway.chat_archive import archive_window_safely
    runtime = GatewayStore(str(tmp_path / 'runtime.db'))
    path = tmp_path / 'archive.db'
    cfg = SimpleNamespace(enable_chat_archive=True, chat_archive_backend='sqlite',
                          chat_archive_db_path=str(path), gateway_db_path=str(runtime.db_path),
                          chat_archive_seen_retention=10000)
    # The archive can fail after startup; constructing the preparation dependency
    # must still succeed. The existing safe side-task reports the failure instead.
    service = ChatArchiveService(runtime, None, cfg)
    assert service.enabled()
    messages = [{'role': 'user', 'content': 'archive failure must not change the reply'}]
    await archive_window_safely(service, session_tag='same', client_name='shenyu-pwa', messages=messages)
    assert 'archive pass failed' in caplog.text
    assert messages[0]['content'] not in caplog.text
    local = LocalChatArchive(path, create=True)
    # A failed archive attempt must not mark the content seen; a later pass retries.
    assert (await service.archive_window(session_tag='same', client_name='shenyu-pwa', messages=messages))['archived'] == 1
    assert local.stats()['total'] == 1
