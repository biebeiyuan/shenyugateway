"""Observation lifetime and exact provider payloads, with no live model calls."""
import base64
from copy import deepcopy
from functools import partial
import json
import sqlite3

import pytest

from shenyu_gateway.album_media import ALBUM_VIEW_KEY, TOOL_IMAGES_KEY, hydrate_album_views
from shenyu_gateway.request_logs import _record_upstream_payload
from shenyu_gateway.schemas import ChatRequest
from shenyu_gateway.tool_loop import run_internal_tool_loop, run_internal_tool_loop_stream
from shenyu_gateway.upstream_adapter import _apply_openai_compatible_cache_control
from shenyu_gateway.upstream_client import build_upstream_request, resolve_upstream
from tests.test_album import _store
from tests.test_album_review import album_call, album_context


def view_message(photo_id, call_id='open-1'):
    return {'role': 'tool', 'tool_call_id': call_id, 'name': 'shenyu_album_open',
            'content': '{"ok":true}', ALBUM_VIEW_KEY: photo_id}


def prompt_content(value):
    # Anthropic's existing tail policy moves the *annotation* forward. Compare
    # model input, not breakpoint placement (covered separately above).
    if isinstance(value, dict):
        return {key: prompt_content(item) for key, item in value.items() if key != 'cache_control'}
    if isinstance(value, list):
        return [prompt_content(item) for item in value]
    return value


def test_view_resolution_is_once_per_action_and_cannot_be_mutated_by_a_payload(tmp_path, monkeypatch):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'private-pixels')
    original = store.album_photo_bytes
    reads = []

    def read(photo_id):
        reads.append(photo_id)
        return original(photo_id)

    monkeypatch.setattr(store, 'album_photo_bytes', read)
    source = [view_message(photo['id'])]
    cache = {}
    first = hydrate_album_views(source, store, view_cache=cache)
    expected = deepcopy(first)
    first[0][TOOL_IMAGES_KEY][0]['image_url']['url'] = 'corrupted by caller'
    for _ in range(4):
        assert hydrate_album_views(deepcopy(source), store, view_cache=cache) == expected
    assert reads == [photo['id']]
    assert 'base64' not in json.dumps(source)
    # Another request owns a fresh memo; this is not a global byte cache.
    assert hydrate_album_views(source, store, view_cache={}) == expected
    assert reads == [photo['id'], photo['id']]


def test_failed_observation_stays_failed_but_a_new_open_can_retry(tmp_path, monkeypatch):
    store = _store(tmp_path)
    photo = store.save_album_photo(raw=b'pixels')
    original = store.album_photo_bytes
    reads = []

    def flaky(photo_id):
        reads.append(photo_id)
        if len(reads) == 1:
            raise sqlite3.OperationalError('temporary read error')
        return original(photo_id)

    monkeypatch.setattr(store, 'album_photo_bytes', flaky)
    cache = {}
    first_source = view_message(photo['id'])
    first = hydrate_album_views([first_source], store, view_cache=cache)[0]
    assert json.loads(first['content'])['ok'] is False
    assert TOOL_IMAGES_KEY not in first
    both = hydrate_album_views([first_source, view_message(photo['id'], 'open-2')], store, view_cache=cache)
    assert both[0] == first
    assert TOOL_IMAGES_KEY in both[1]
    assert len(reads) == 2


@pytest.mark.parametrize('guard', [0, 1, 2])
def test_synthetic_observations_do_not_move_real_user_tail_breakpoints(guard):
    source = [
        {'role': 'user', 'content': 'first real user'},
        {'role': 'assistant', 'content': 'first reply'},
        {'role': 'user', 'content': 'second real user'},
        {'role': 'assistant', 'content': 'second reply'},
        {'role': 'user', 'content': 'third real user'},
    ]
    plain, _, plain_paths = _apply_openai_compatible_cache_control(source, [], tail_guard_user_turns=guard)
    calls = [album_call('open', 'phot_one', 'open-1')]
    with_view = [*deepcopy(source), {'role': 'assistant', 'content': '', 'tool_calls': calls}, {
        'role': 'tool', 'tool_call_id': 'open-1', 'content': '{}',
        TOOL_IMAGES_KEY: [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}],
    }]
    wire, _, paths = _apply_openai_compatible_cache_control(with_view, [], tail_guard_user_turns=guard)
    assert paths == plain_paths
    assert wire[:len(source)] == plain
    assert wire[-1]['role'] == 'user'
    assert wire[-1]['content'][-1]['type'] == 'image_url'
    assert 'cache_control' not in json.dumps(wire[-1])
    assert '_shenyu_' not in json.dumps(wire)


@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('cache_enabled', [False, True])
async def test_multiround_payload_keeps_old_observation_stable_and_retries_only_new_open(
    tmp_path, monkeypatch, protocol, stream, cache_enabled,
):
    store = _store(tmp_path)
    ctx = album_context(store)
    ctx.cfg.max_internal_tool_rounds = 4
    ctx.cfg.enable_openai_cache_control = cache_enabled
    ctx.cfg.enable_anthropic_cache_control = cache_enabled
    ctx.body = ChatRequest(model='test-model', messages=[{'role': 'user', 'content': '翻相册'}])
    ctx.request.headers = {}
    ctx.prepared_messages = [{'role': 'user', 'content': '翻相册'}]
    ctx.meta['upstream'] = {**resolve_upstream(ctx.cfg), 'protocol': protocol}
    ctx.build_upstream_request = partial(build_upstream_request, cfg=ctx.cfg)
    ctx.record_upstream_payload = _record_upstream_payload
    raw = b'observation-pixels-not-history'
    encoded = base64.b64encode(raw).decode()
    photo = store.save_album_photo(raw=raw)
    original_read = store.album_photo_bytes
    reads = []

    def read_then_fail(photo_id):
        reads.append(photo_id)
        if len(reads) > 1:
            raise sqlite3.OperationalError('later read failed')
        return original_read(photo_id)

    monkeypatch.setattr(store, 'album_photo_bytes', read_then_fail)
    calls = [
        album_call('open', photo['id'], 'open-1', 'broker'),
        {'id': 'list-1', 'type': 'function', 'function': {
            'name': 'shenyu_album_list', 'arguments': '{"limit":1}'}},
        album_call('open', photo['id'], 'open-2', 'broker'),
    ]
    payloads = []

    async def call_json(request, url, payload, headers):
        payloads.append(deepcopy(payload))
        index = len(payloads) - 1
        call = calls[index] if index < len(calls) else None
        if protocol == 'anthropic':
            content = [{'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'],
                        'input': json.loads(call['function']['arguments'])}] if call else [{'type': 'text', 'text': '看过了'}]
            return {'id': 'response', 'type': 'message', 'role': 'assistant', 'content': content,
                    'stop_reason': 'tool_use' if call else 'end_turn', 'usage': {}}
        return {'choices': [{'message': {'role': 'assistant', 'content': '' if call else '看过了',
                            **({'tool_calls': [call]} if call else {})},
                            'finish_reason': 'tool_calls' if call else 'stop'}], 'usage': {}}

    async def chunks(request, payload, headers, model, upstream):
        payloads.append(deepcopy(payload))
        index = len(payloads) - 1
        call = calls[index] if index < len(calls) else None
        yield {'choices': [{'index': 0, 'delta': {'tool_calls': [{**call, 'index': 0}]} if call else {'content': '看过了'},
                            'finish_reason': 'tool_calls' if call else 'stop'}]}

    ctx.call_upstream_json, ctx.stream_upstream_openai_chunks = call_json, chunks
    if stream:
        wire = ''.join([part async for part in run_internal_tool_loop_stream(ctx)])
    else:
        wire = json.dumps(await run_internal_tool_loop(ctx))
    assert len(payloads) == 4
    assert reads == [photo['id'], photo['id']]
    assert encoded in json.dumps(payloads[1])
    for previous, current in zip(payloads[1:], payloads[2:]):
        assert prompt_content(current['messages'][:len(previous['messages'])]) == prompt_content(previous['messages'])
    # New observation can fail without changing the first successful one.
    assert encoded in json.dumps(payloads[-1])
    assert '尚未看到画面' in json.dumps(payloads[-1], ensure_ascii=False)
    assert encoded not in wire
    assert encoded not in json.dumps(ctx.meta)
    assert encoded not in json.dumps(ctx.log_entry)
    assert encoded not in json.dumps(store.get_recent_messages(ctx.session_id, limit=50))