import base64
import os

import pytest

from shenyu_gateway.gateway_tools import AlbumToolsMixin, latest_turn_images
from shenyu_gateway.gateway_tools._album import _decode_image_block
from shenyu_gateway.store import DEFAULT_ALBUM_NAME, GatewayStore, photo_fingerprint


def _store(tmp_path) -> GatewayStore:
    return GatewayStore(str(tmp_path / "album.db"))


def _data_url(raw: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _user_turn(*raws: bytes, text: str = "看这个") -> dict:
    blocks = [{"type": "text", "text": text}]
    for raw in raws:
        blocks.append({"type": "image_url", "image_url": {"url": _data_url(raw)}})
    return {"role": "user", "content": blocks}


class FakeSupabase:
    def __init__(self, fail: bool = False):
        self.inserts: list[tuple[str, dict]] = []
        self.fail = fail
        self._next = 0

    async def insert(self, table: str, data: dict) -> dict:
        if self.fail:
            raise RuntimeError("supabase unavailable")
        self.inserts.append((table, dict(data)))
        self._next += 1
        return {"id": f"note-uuid-{self._next}", **data}


class FakeRecallIndex:
    def __init__(self):
        self.rows: list[dict] = []

    async def index_album_note_row(self, row: dict) -> dict:
        self.rows.append(dict(row))
        return {"ok": True, "indexed": 1}


class AlbumService(AlbumToolsMixin):
    """只装相册这一个 mixin，避开完整 GatewayToolService 的运行时依赖。"""

    def __init__(self, store, supabase=None, recall=None):
        self.store = store
        self.supabase = supabase
        self.cfg = None
        self._recall = recall or FakeRecallIndex()

    def _recall_index(self):
        return self._recall


# ── 本机存储 ──────────────────────────────────────────────────────────


def test_photos_and_notes_round_trip(tmp_path):
    store = _store(tmp_path)
    raw = os.urandom(2048)
    saved = store.save_album_photo(raw=raw, note="海边那天的光", mood="安静")

    assert saved["book_name"] == DEFAULT_ALBUM_NAME
    assert saved["byte_size"] == len(raw)
    assert store.album_photo_bytes(saved["id"])["bytes"] == raw

    books = store.list_album_books()
    assert [book["name"] for book in books] == [DEFAULT_ALBUM_NAME]
    assert books[0]["photo_count"] == 1


def test_photo_listing_never_carries_image_bytes(tmp_path):
    """列表是翻相册用的；把 blob 一起读出来会让一次请求搬走几十 MB。"""
    store = _store(tmp_path)
    store.save_album_photo(raw=os.urandom(4096), note="一句话")

    rows = store.list_album_photos()
    assert rows
    for row in rows:
        assert "bytes" not in row
        assert row["byte_size"] == 4096


def test_photo_size_limit_is_enforced(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="larger than"):
        store.save_album_photo(raw=os.urandom(3 * 1024 * 1024))


def test_fingerprint_matches_the_pwa_algorithm():
    """两侧必须是同一个算法，否则过期后网关永远认不出相册里那张图。

    PWA 侧同一断言在 `pwa/tests/photoStore.spec.ts`（crypto.subtle SHA-256）。
    改动任一侧都会让其中一个测试变红。
    """
    assert photo_fingerprint(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_lookup_by_fingerprint_returns_the_note(tmp_path):
    """过期回填的入口：给指纹，拿回沈予当时写的话。"""
    store = _store(tmp_path)
    raw = os.urandom(1024)
    store.save_album_photo(raw=raw, note="想留住这个", mood="高兴", book_name="想留的")

    found = store.album_notes_by_fingerprints([photo_fingerprint(raw), "no-such-digest"])
    assert list(found) == [photo_fingerprint(raw)]
    assert found[photo_fingerprint(raw)]["note"] == "想留住这个"
    assert found[photo_fingerprint(raw)]["book_name"] == "想留的"


def test_fingerprint_lookup_keeps_the_newest_note_for_one_image(tmp_path):
    store = _store(tmp_path)
    raw = os.urandom(1024)
    store.save_album_photo(raw=raw, note="第一次存")
    store.save_album_photo(raw=raw, note="后来改了主意")

    found = store.album_notes_by_fingerprints([photo_fingerprint(raw)])
    assert found[photo_fingerprint(raw)]["note"] == "后来改了主意"


def test_empty_fingerprint_list_does_not_query(tmp_path):
    assert _store(tmp_path).album_notes_by_fingerprints([]) == {}
    assert _store(tmp_path).album_notes_by_fingerprints(["", "  "]) == {}


# ── 从消息里取图 ──────────────────────────────────────────────────────


def test_latest_turn_images_reads_the_newest_image_turn():
    """"存这张"不需要正文里的标记——模型此刻正看着图，最新那轮就是它。"""
    old, new = os.urandom(64), os.urandom(64)
    messages = [
        _user_turn(old, text="早些的图"),
        {"role": "assistant", "content": "好看"},
        _user_turn(new, text="刚发的图"),
    ]
    blocks = latest_turn_images(messages)
    assert len(blocks) == 1
    assert _decode_image_block(blocks[0])[0] == new


def test_latest_turn_images_ignores_expired_fingerprint_blocks():
    """过期图被换成 fingerprint 占位块，那里面没有字节，不能当成可存的图。"""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "旧图"},
                {"type": "image", "source": {"type": "shenyu_history_image", "fingerprint": "abc"}},
            ],
        }
    ]
    assert latest_turn_images(messages) == []


def test_latest_turn_images_tolerates_odd_shapes():
    assert latest_turn_images(None) == []
    assert latest_turn_images([]) == []
    assert latest_turn_images([{"role": "user", "content": "纯文字"}]) == []
    assert latest_turn_images([{"role": "assistant", "content": [{"type": "image_url", "image_url": {"url": _data_url(b"x")}}]}]) == []


def test_decode_handles_anthropic_source_blocks():
    raw = os.urandom(32)
    block = {"type": "image", "source": {"media_type": "image/png", "data": base64.b64encode(raw).decode()}}
    assert _decode_image_block(block) == (raw, "image/png")


def test_decode_rejects_broken_payloads():
    assert _decode_image_block({"image_url": {"url": "data:image/jpeg;base64,"}}) is None
    assert _decode_image_block({"type": "text", "text": "x"}) is None


# ── 工具行为 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_album_save_stores_image_locally_and_note_in_supabase(tmp_path):
    store = _store(tmp_path)
    supabase = FakeSupabase()
    recall = FakeRecallIndex()
    service = AlbumService(store, supabase, recall)
    raw = os.urandom(1024)

    result = await service.album_save(
        note="海边那天的光",
        mood="安静",
        images=latest_turn_images([_user_turn(raw)]),
        session_tag="tag-1",
    )

    assert result["ok"] is True
    assert result["data"]["note_searchable"] is True
    # 图在本机。
    assert store.album_photo_bytes(result["data"]["photo_id"])["bytes"] == raw
    # 备注在 Supabase，且只有文字——图片字节绝不出现在那边。
    table, row = supabase.inserts[0]
    assert table == "shenyu_album_notes"
    assert row["note"] == "海边那天的光"
    assert not any(isinstance(value, (bytes, bytearray)) for value in row.values())
    assert "bytes" not in row and "data" not in row
    # 备注进了 Recall，所以以后聊到海边它能自己想起来。
    assert recall.rows[0]["note"] == "海边那天的光"
    # 两边靠 note_ref 对上。
    assert store.list_album_photos()[0]["note_ref"] == "note-uuid-1"


@pytest.mark.asyncio
async def test_album_save_keeps_the_photo_when_supabase_is_down(tmp_path):
    """备注同步失败不该让图也丢掉：图在本机是既成事实。"""
    store = _store(tmp_path)
    service = AlbumService(store, FakeSupabase(fail=True))
    raw = os.urandom(512)

    result = await service.album_save(note="还是想留着", images=latest_turn_images([_user_turn(raw)]))

    assert result["ok"] is True
    assert result["data"]["note_searchable"] is False
    assert store.album_photo_bytes(result["data"]["photo_id"])["bytes"] == raw


@pytest.mark.asyncio
async def test_album_save_picks_the_requested_image_of_the_turn(tmp_path):
    store = _store(tmp_path)
    service = AlbumService(store, FakeSupabase())
    first, second = os.urandom(64), os.urandom(64)

    result = await service.album_save(
        which=2,
        note="第二张",
        images=latest_turn_images([_user_turn(first, second)]),
    )

    assert store.album_photo_bytes(result["data"]["photo_id"])["bytes"] == second


@pytest.mark.asyncio
async def test_album_save_explains_when_there_is_no_image(tmp_path):
    service = AlbumService(_store(tmp_path), FakeSupabase())
    result = await service.album_save(note="想存点什么", images=[])
    assert result["ok"] is False
    assert result["error_kind"] == "validation"
    assert "没有看到图片" in result["error"]


@pytest.mark.asyncio
async def test_album_save_explains_an_out_of_range_index(tmp_path):
    service = AlbumService(_store(tmp_path), FakeSupabase())
    result = await service.album_save(which=5, images=latest_turn_images([_user_turn(os.urandom(32))]))
    assert result["ok"] is False
    assert "只有 1 张图" in result["error"]


@pytest.mark.asyncio
async def test_album_save_without_note_skips_supabase_entirely(tmp_path):
    """没写字就没有可检索的东西，不该往 Supabase 塞空行。"""
    store = _store(tmp_path)
    supabase = FakeSupabase()
    service = AlbumService(store, supabase)

    result = await service.album_save(images=latest_turn_images([_user_turn(os.urandom(64))]))

    assert result["ok"] is True
    assert supabase.inserts == []
    assert result["data"]["note_searchable"] is False


def test_album_api_serves_listings_and_one_immutable_bytes_route(tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shenyu_gateway.gateway_admin_routes import GatewayAdminRouteDeps, build_gateway_admin_router

    store = _store(tmp_path)
    raw = os.urandom(4096)
    saved = store.save_album_photo(raw=raw, mime="image/png", note="海边那天的光", book_name="想留的")

    app = FastAPI()
    app.include_router(
        build_gateway_admin_router(
            GatewayAdminRouteDeps(
                cfg=SimpleNamespace(gateway_key=""),
                get_supabase_client=lambda: None,
                get_session_store=lambda: store,
                require_session_store=lambda: store,
                context_builder=lambda *args: None,
                resolve_upstream=lambda: {},
                prune_runtime_state=lambda **kwargs: {},
                cold_start_idle_minutes=lambda session: 0.0,
                now=lambda: None,
                request_logs=None,
            )
        )
    )
    client = TestClient(app)

    books = client.get("/api/gateway/album").json()
    assert [book["name"] for book in books["books"]] == ["想留的"]
    assert books["books"][0]["photo_count"] == 1

    listing = client.get("/api/gateway/album", params={"book": "想留的"}).json()
    assert listing["photos"][0]["note"] == "海边那天的光"
    # 列表绝不带 blob：翻相册不该搬走几十 MB。
    assert "bytes" not in listing["photos"][0]

    photo = client.get(f"/api/gateway/album/photo/{saved['id']}")
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/png"
    assert photo.content == raw
    # 按 id 寻址、内容不会改写，所以可以长缓存；private 避免中间层留存。
    assert "immutable" in photo.headers["cache-control"]
    assert "private" in photo.headers["cache-control"]

    assert client.get("/api/gateway/album/photo/no-such-photo").status_code == 404


@pytest.mark.asyncio
async def test_album_list_shows_books_then_photos(tmp_path):
    store = _store(tmp_path)
    service = AlbumService(store, FakeSupabase())
    store.save_album_photo(raw=os.urandom(64), note="一", book_name="想留的")
    store.save_album_photo(raw=os.urandom(64), note="二", book_name="我们俩")

    books = await service.album_list()
    assert {book["name"] for book in books["data"]["books"]} == {"想留的", "我们俩"}

    photos = await service.album_list(book="我们俩")
    assert [photo["note"] for photo in photos["data"]["photos"]] == ["二"]
    assert all("bytes" not in photo for photo in photos["data"]["photos"])
