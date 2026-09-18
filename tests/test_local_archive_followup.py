from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from shenyu_gateway.local_chat_archive import LocalChatArchive


ROOT = Path(__file__).resolve().parents[1]
TOMBSTONE = '2026-09-19T00:00:00+00:00'


def original(ident: str, *, event: str = '2026-09-17T01:00:00+00:00',
             archived: str = '2026-09-17T02:00:00+00:00') -> dict:
    return {'id': ident, 'session_tag': 'A', 'thread': 'A',
            'client_name': 'shenyu-pwa', 'role': 'user', 'content': '测试 needle',
            'content_hash': 'same-words', 'event_at': event,
            'archived_at': archived, 'deleted_at': None}


@pytest.mark.parametrize('order_key', ['event', 'archive', 'id'])
@pytest.mark.parametrize('deleted_mask', range(8))
@pytest.mark.parametrize('reimport', [False, True])
def test_partial_tombstones_have_one_earliest_live_representative(
        tmp_path, order_key, deleted_mask, reimport):
    """A deleted first copy must promote only the next live copy, not all copies."""
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    copies = [original(ident) for ident in ('a', 'b', 'c')]
    for index, row in enumerate(copies):
        if order_key == 'event':
            row['event_at'] = f'2026-09-17T01:00:0{index}+00:00'
        elif order_key == 'archive':
            row['archived_at'] = f'2026-09-17T02:00:0{index}+00:00'
    if reimport:
        store.import_rows(reversed(copies))
    for index, row in enumerate(copies):
        if deleted_mask & (1 << index):
            row['deleted_at'] = TOMBSTONE
    # Same words on a different day are a separate legacy group.
    other_day = original('other-day', event='2026-09-18T01:00:00+00:00')
    source = [*copies, other_day]
    store.import_rows(reversed(source))
    surviving = [row for row in copies if row['deleted_at'] is None]
    expected_ids = ([surviving[0]['id']] if surviving else []) + ['other-day']

    assert store.stats() == {'total': 4, 'active': len(surviving) + 1,
                             'visible': len(expected_ids)}
    expected_days = ([{'date': '2026-09-17', 'count': 1}] if surviving else [])
    expected_days.append({'date': '2026-09-18', 'count': 1})
    assert store.days('2026-09') == expected_days
    assert sum(day['count'] for day in store.days()) == store.stats()['visible']
    listed = store.list_messages()
    assert [row['id'] for row in listed] == expected_ids
    assert [row['id'] for row in store.search('测试')['results']] == expected_ids[::-1]
    # Reader folding is presentation only; all originals and tombstones survive.
    assert store.export_rows() == sorted(source, key=lambda row: row['id'])
    if surviving:
        cursor = store.cursor(listed[0])
        assert [row['id'] for row in store.list_messages(after=cursor)] == ['other-day']


@pytest.mark.parametrize(('limit', 'message_count', 'search_count'), [
    (-10, 1, 1), (0, 200, 1), (1, 1, 1), (60, 60, 60),
    (200, 200, 200), (500, 500, 200), (2000, 1000, 200),
])
def test_archive_limits_share_clamping_without_changing_endpoint_contracts(
        tmp_path, limit, message_count, search_count):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows(original(f'{index:04d}') for index in range(1001))
    assert len(store.list_messages(limit=limit)) == message_count
    result = store.search('needle', limit=limit)
    assert result['count'] == search_count
    assert result['has_more'] is True
    assert result['next_cursor'] is not None


def test_archive_endpoint_default_page_sizes_remain_distinct(tmp_path):
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows(original(f'{index:04d}') for index in range(201))
    assert len(store.list_messages()) == 200
    assert store.search('needle')['count'] == 60


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('predicate_drift', [False, True])
def test_search_guard_and_normal_results_do_not_depend_on_python_asserts(
        tmp_path, optimized, predicate_drift):
    """Inject predicate drift only to exercise the otherwise unreachable guard."""
    store = LocalChatArchive(tmp_path / 'archive.db', create=True)
    store.append_rows([original('a')])
    script = r'''
import re
import sys
from unittest.mock import patch
from shenyu_gateway import local_chat_archive as module

store = module.LocalChatArchive(sys.argv[1])
if sys.argv[2] == 'normal':
    result = store.search('needle')
    if result['count'] != 1 or result['results'][0]['snippet_match'] != 'needle':
        raise RuntimeError('optimized search changed normal results')
else:
    real_search = re.compile('needle', re.IGNORECASE).search

    class PredicateDrift:
        calls = 0

        def search(self, text):
            self.calls += 1
            # SQLite accepts the row; simulate a later invariant violation.
            return real_search(text) if self.calls == 1 else None

    with patch.object(module.re, 'compile', return_value=PredicateDrift()):
        try:
            store.search('needle')
        except RuntimeError as exc:
            if str(exc) != 'archive search predicate mismatch':
                raise
        else:
            raise RuntimeError('search silently accepted predicate drift')
'''
    command = [sys.executable, *(['-O'] if optimized else []), '-c', script,
               str(store.path), 'drift' if predicate_drift else 'normal']
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
