-- 家现在 is a generated snapshot, not a writable living document.
-- Keep its row only as the stable foreign-key anchor for append-only annotations.
-- Existing body/revision data is deliberately preserved but no longer read or written.

alter table shenyu_books
  drop constraint if exists shenyu_books_kind_check;

alter table shenyu_books
  add constraint shenyu_books_kind_check check (kind in ('living', 'snapshot'));

update shenyu_books
set kind = 'snapshot'
where slug = 'home';
