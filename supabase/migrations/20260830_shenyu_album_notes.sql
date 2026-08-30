-- 沈予相册的备注。图片字节留在网关本机卷的 SQLite（生产是 named volume
-- shenyu-gateway-data 挂在 /data），这里只存他自己写的那句话。
--
-- 分开住的理由有两条：Recall 的全部数据源都只读 Supabase（recall/_sources.py
-- 里没有任何 SQLite 适配器），所以要让备注能被想起来就必须在这边；而万一本机
-- 卷出事，丢的是图，他写的话还在——那半更难重建。

create extension if not exists pgcrypto;

create table if not exists shenyu_album_notes (
  id uuid primary key default gen_random_uuid(),
  -- 本机 album_photos.id，两边靠它对上。
  photo_id text not null unique,
  book_name text not null default '',
  note text not null default '',
  mood text not null default '',
  -- 图片字节的 sha256。过期回填时网关用它认出这张图是相册里的哪一张。
  fingerprint text not null default '',
  saved_at timestamptz not null default now(),
  constraint shenyu_album_notes_has_text
    check (btrim(note) <> '' or btrim(mood) <> '')
);

create index if not exists shenyu_album_notes_saved_at_idx
  on shenyu_album_notes (saved_at desc);

create index if not exists shenyu_album_notes_fingerprint_idx
  on shenyu_album_notes (fingerprint)
  where btrim(fingerprint) <> '';

create index if not exists shenyu_album_notes_book_saved_idx
  on shenyu_album_notes (book_name, saved_at desc)
  where btrim(book_name) <> '';
