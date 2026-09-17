from __future__ import annotations

"""Explicit local-archive migration/backup commands. No deployment or scheduling.

Only source-export accesses Supabase, read-only; it never prints original text.
Imports preview by default, fail on conflicting immutable rows, and preserve IDs.
Do not use a live-changing source export as proof that a cutover is complete.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shenyu_gateway.local_chat_archive import LocalChatArchive

SOURCE_COLUMNS = 'id,session_tag,thread,client_name,role,content,content_hash,event_at,archived_at,deleted_at'


def _read_source(path: Path) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    with path.open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                LocalChatArchive._validated(row, legacy=True)
            except (ValueError, TypeError) as exc:
                # JSONDecodeError embeds original content. Never print it.
                raise ValueError(f'invalid archive source at line {line_number}') from exc
            if row['id'] in seen:
                raise ValueError(f'duplicate source ID at line {line_number}')
            seen.add(row['id'])
            rows.append(row)
    return rows


def _write_export(path: Path, rows: list[dict]) -> dict[str, Any]:
    if path.exists() or path.is_symlink():
        raise FileExistsError('export destination already exists')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.archive-export-', dir=path.parent)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, 'wb') as output:
            for row in rows:
                raw = (json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
                digest.update(raw)
                output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'rows': len(rows), 'sha256': digest.hexdigest()}


async def source_export(output: Path) -> dict[str, Any]:
    from shenyu_gateway.config import RuntimeConfig
    from shenyu_gateway.supabase import SupabaseClient
    cfg = RuntimeConfig()
    if not cfg.supabase_url or not cfg.supabase_key:
        raise ValueError('Supabase is not configured')
    client = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    rows: list[dict] = []
    after = None
    try:
        while True:
            params = {'select': SOURCE_COLUMNS, 'order': 'id.asc', 'limit': '1000'}
            if after:
                params['id'] = f'gt.{after}'
            # Include soft-deleted rows; UUID keyset avoids offset pagination loss.
            page = await client.query('shenyu_chat_archive', params=params)
            if not page:
                break
            for row in page:
                LocalChatArchive._validated(row, legacy=True)
            next_after = page[-1]['id']
            if after is not None and next_after <= after:
                raise ValueError('source cursor failed to advance')
            rows.extend(page)
            after = next_after
    finally:
        await client.close()
    return _write_export(output, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, help='Separate archive DB; never the gateway runtime DB')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init', help='Explicitly initialize an EMPTY archive (new installations only)')
    sub.add_parser('stats', help='Read counts only')
    for command in ('import-jsonl', 'verify'):
        item = sub.add_parser(command)
        item.add_argument('--source', required=True, type=Path)
        if command == 'import-jsonl':
            item.add_argument('--apply', action='store_true', help='Write after preview; default is read-only')
    for command in ('export', 'backup', 'source-export'):
        item = sub.add_parser(command)
        item.add_argument('--output', required=True, type=Path)
        if command == 'source-export':
            item.add_argument('--confirm-source-paused', required=True, action='store_true',
                              help='Confirm archive writes/deletions are paused for a consistent source export')
    args = parser.parse_args(argv)
    if args.command != 'source-export' and args.db is None:
        parser.error('--db is required for local commands')
    try:
        if args.command == 'source-export':
            result = asyncio.run(source_export(args.output))
        elif args.command == 'import-jsonl':
            rows = _read_source(args.source)
            store = LocalChatArchive(args.db) if args.db.exists() else None
            existing = {row['id']: row for row in store.export_rows()} if store else {}
            for row in rows:
                old = existing.get(row['id'])
                if old and any(old[key] != row.get(key) for key in old if key != 'deleted_at'):
                    raise ValueError(f'archive original conflict for id {row["id"]}')
            count = sum(row['id'] not in existing for row in rows)
            if not args.apply:
                result = {'mode': 'dry-run', 'source_rows': len(rows), 'would_insert': count}
            else:
                store = store or LocalChatArchive(args.db, create=True)
                inserted = store.import_rows(rows)
                result = {'mode': 'applied', 'inserted': inserted, **store.stats(),
                          'next': 'verify against the final paused-source export before cutover'}
        elif args.command == 'init':
            result = LocalChatArchive(args.db, create=True).stats()
        else:
            store = LocalChatArchive(args.db)
            if args.command == 'verify':
                result = {'verified': True, **store.verify_rows(_read_source(args.source))}
            elif args.command == 'stats':
                result = store.stats()
            elif args.command == 'export':
                result = _write_export(args.output, store.export_rows())
            else:
                path = store.backup(args.output)
                # Hash the completed private snapshot, not a live-changing source file.
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                result = {'backup_created': True, 'sha256': digest, 'bytes': path.stat().st_size}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError) as exc:
        print(f'Archive command failed: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:
        # Upstream errors can contain response bodies, URLs and credentials.
        print(f'Archive command failed ({type(exc).__name__}); no source text was logged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
