from __future__ import annotations

import importlib.util
import json

from shenyu_gateway.local_chat_archive import LocalChatArchive
from .test_local_chat_archive import row


def cli():
    assert importlib.util.find_spec('scripts.local_chat_archive') is not None, 'archive CLI is not implemented'
    from scripts.local_chat_archive import main
    return main


def write_source(path):
    path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in [row('a'),row('b','再见')])+'\n',encoding='utf-8')


def test_import_dry_run_does_not_create_a_database(tmp_path,capsys):
    source=tmp_path/'source.jsonl'; write_source(source)
    destination=tmp_path/'new'/'archive.db'
    assert cli()(['--db',str(destination),'import-jsonl','--source',str(source)])==0
    assert not destination.exists() and not destination.parent.exists()
    assert json.loads(capsys.readouterr().out)['mode']=='dry-run'


def test_import_verify_export_and_backup_roundtrip(tmp_path,capsys):
    source=tmp_path/'source.jsonl'; write_source(source)
    database=tmp_path/'archive.db'
    assert cli()(['--db',str(database),'import-jsonl','--source',str(source),'--apply'])==0
    assert cli()(['--db',str(database),'verify','--source',str(source)])==0
    output=tmp_path/'export.jsonl'
    assert cli()(['--db',str(database),'export','--output',str(output)])==0
    assert [json.loads(s) for s in output.read_text().splitlines()]==LocalChatArchive(database).export_rows()
    backup=tmp_path/'backup.db'
    assert cli()(['--db',str(database),'backup','--output',str(backup)])==0
    assert LocalChatArchive(backup).export_rows()==LocalChatArchive(database).export_rows()
    assert output.stat().st_mode & 0o077 == 0
    assert '今天和沈予聊天' not in capsys.readouterr().out


def test_conflicting_source_dry_run_is_read_only_and_fails(tmp_path,capsys):
    database=tmp_path/'archive.db'
    store=LocalChatArchive(database,create=True); store.import_rows([row()])
    source=tmp_path/'conflict.jsonl'; source.write_text(json.dumps(row(content='changed')),encoding='utf-8')
    assert cli()(['--db',str(database),'import-jsonl','--source',str(source)])==1
    assert store.export_rows()==[row()]
    assert 'changed' not in capsys.readouterr().err


def test_export_refuses_to_overwrite(tmp_path):
    database=tmp_path/'archive.db'; LocalChatArchive(database,create=True)
    output=tmp_path/'export.jsonl'; output.write_text('keep')
    assert cli()(['--db',str(database),'export','--output',str(output)])==1
    assert output.read_text()=='keep'
