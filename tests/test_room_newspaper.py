from __future__ import annotations

import asyncio
import json
import random
from types import SimpleNamespace

import httpx

from shenyu_gateway.room_newspaper import (
    FeedSource,
    NewspaperItem,
    RoomNewspaperService,
    parse_feed,
    roll_issue_candidates,
)
from shenyu_gateway.room_tools import execute_room_tool
from shenyu_gateway.store import GatewayStore


def _item(index: int, source_id: str, bucket: str) -> NewspaperItem:
    return NewspaperItem(
        candidate_id=f"candidate-{index}",
        source_id=source_id,
        source_name=source_id,
        bucket=bucket,
        title=f"Title {index}",
        summary=f"Sentence one for {index}. Sentence two. Sentence three.",
        url=f"https://example.test/{index}",
        guid=f"guid-{index}",
        published_at="2026-07-14T00:00:00+00:00",
    )


def _stored_items(start: int = 0) -> list[dict[str, str]]:
    result = []
    for offset in range(5):
        item = _item(start + offset, "hacker_news" if offset < 4 else "nasa_apod", "interest" if offset < 4 else "random")
        result.append(item.to_dict())
    return result


def test_parse_feed_keeps_source_text_and_limits_summary_to_three_sentences():
    source = FeedSource("quanta", "Quanta Magazine", "https://example.test/feed", "interest")
    feed = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <title>Original &amp; Untouched</title>
      <link>https://example.test/story?utm_source=rss&amp;keep=yes</link>
      <description><![CDATA[<p>First sentence. Second sentence! Third sentence?</p><p>Fourth sentence.</p>]]></description>
      <pubDate>Tue, 14 Jul 2026 08:00:00 +0000</pubDate>
      <guid>story-1</guid>
    </item></channel></rss>"""

    items = parse_feed(feed, source)

    assert len(items) == 1
    assert items[0].title == "Original & Untouched"
    assert items[0].summary == "First sentence. Second sentence! Third sentence?"
    assert items[0].url == "https://example.test/story?keep=yes"
    assert items[0].published_at.startswith("2026-07-14T08:00:00")


def test_parse_apod_uses_feed_alt_text_without_inventing_description():
    source = FeedSource("nasa_apod", "NASA APOD", "https://apod.nasa.gov/apod.rss", "random")
    feed = b"""<rss><channel><item>
      <title></title>
      <link>https://apod.nasa.gov/apod/ap260714.html</link>
      <description>&lt;p&gt;&lt;img src="S_260714.jpg" alt="Why is this asteroid a double?" /&gt; Why is this asteroid a double?&lt;/p&gt;</description>
    </item></channel></rss>"""

    items = parse_feed(feed, source)

    assert items[0].title == "Why is this asteroid a double?"
    assert items[0].summary == "Why is this asteroid a double?"
    assert items[0].published_at.startswith("2026-07-14T00:00:00")


def test_parse_feed_removes_wordpress_delivery_boilerplate_only():
    source = FeedSource("nautilus", "Nautilus", "https://nautil.us/feed/", "interest")
    feed = b"""<rss><channel><item>
      <title>Giant salamander</title>
      <link>https://nautil.us/giant-salamander/</link>
      <description>And it has a living relative The post Giant salamander appeared first on Nautilus .</description>
    </item></channel></rss>"""

    items = parse_feed(feed, source)

    assert items[0].summary == "And it has a living relative"


def test_roll_issue_uses_eight_two_mix_and_caps_source_repetition():
    items = []
    interest_sources = ["hacker_news", "lobsters", "arxiv_ai", "arxiv_cl", "quanta"]
    random_sources = ["hakai", "sciencedaily_animals", "nasa_apod"]
    index = 0
    for source_id in interest_sources:
        for _ in range(4):
            items.append(_item(index, source_id, "interest"))
            index += 1
    for source_id in random_sources:
        for _ in range(4):
            items.append(_item(index, source_id, "random"))
            index += 1

    chosen, interest_count, random_count = roll_issue_candidates(
        items,
        issue_size=8,
        rng=random.Random(7),
    )

    assert (interest_count, random_count) == (6, 2)
    assert sum(item.bucket == "interest" for item in chosen) == 6
    assert sum(item.bucket == "random" for item in chosen) == 2
    assert max(sum(item.source_id == source_id for item in chosen) for source_id in interest_sources + random_sources) <= 2


def test_room_newspaper_store_lifecycle_and_global_url_dedupe(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    first = store.create_room_newspaper_issue(_stored_items(), source_status=[], qa_detail={"used": False})

    assert first["status"] == "draft"
    assert first["interest_count"] == 4
    assert first["random_count"] == 1
    assert store.has_undelivered_room_newspaper() is False

    published = store.publish_room_newspaper_issue(first["id"])
    assert published and published["status"] == "published"
    assert store.has_undelivered_room_newspaper() is True

    delivered = store.mark_room_newspaper_delivered(first["id"])
    assert delivered and delivered["delivered_at"]
    assert store.has_undelivered_room_newspaper() is False
    assert "https://example.test/0" in store.used_room_newspaper_urls()

    second = store.create_room_newspaper_issue(_stored_items(10))
    assert store.latest_published_room_newspaper()["id"] == first["id"]
    store.publish_room_newspaper_issue(second["id"])
    assert store.get_room_newspaper_issue(first["id"])["status"] == "archived"
    assert store.latest_published_room_newspaper()["id"] == second["id"]


def test_sit_by_window_returns_published_issue_and_marks_it_delivered(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    session = store.get_or_create_session("room", "operit")
    draft = store.create_room_newspaper_issue(_stored_items())
    store.publish_room_newspaper_issue(draft["id"])

    result = asyncio.run(
        execute_room_tool(
            "room_sit_by_window",
            {},
            store=store,
            cfg=SimpleNamespace(),
            session_id=session["id"],
            session_tag="room",
        )
    )

    assert result["ok"] is True
    assert result["newspaper"]["item_count"] == 5
    assert result["newspaper"]["items"][0]["title"] == "Title 0"
    assert result["newspaper"]["items"][0]["source"] == "hacker_news"
    assert store.latest_published_room_newspaper()["delivered_at"]
    assert store.recent_room_traces(1)[0]["action"] == "sit"


def test_fetch_candidates_reports_each_source_without_scraping_pages(tmp_path):
    feed = b"""<rss><channel><item>
      <title>Feed title</title><link>https://example.test/feed-title</link>
      <description>Two clean sentences. From RSS only.</description>
      <pubDate>Tue, 14 Jul 2026 08:00:00 +0000</pubDate>
    </item></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/feed.xml"
        return httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"})

    source = FeedSource("test_feed", "Test Feed", "https://feed.test/feed.xml", "interest")
    store = GatewayStore(str(tmp_path / "gateway.db"))
    service = RoomNewspaperService(SimpleNamespace(), store, sources=[source])
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run_fetch():
        try:
            return await service.fetch_candidates(client)
        finally:
            await client.aclose()

    items, statuses = asyncio.run(run_fetch())

    assert [item.title for item in items] == ["Feed title"]
    assert statuses == [{
        "source_id": "test_feed",
        "name": "Test Feed",
        "url": "https://feed.test/feed.xml",
        "bucket": "interest",
        "archive": False,
        "ok": True,
        "count": 1,
        "summary_count": 1,
        "latest_published_at": "2026-07-14T08:00:00+00:00",
    }]


def test_optional_quality_model_can_only_drop_known_candidate_ids(tmp_path):
    response_body = {
        "choices": [{
            "message": {
                "content": '{"drop":[{"id":"candidate-1","reason":"duplicate"},'
                '{"id":"made-up","reason":"ignore"}]}'
            }
        }]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        assert "Do not rewrite, translate, summarize" in prompt
        return httpx.Response(200, json=response_body)

    cfg = SimpleNamespace(
        room_newspaper_qa_enabled=True,
        room_newspaper_llm_model="small-editor",
        room_newspaper_llm_url="https://model.test/v1",
        room_newspaper_llm_api_key="secret",
        room_newspaper_llm_protocol="openai",
        upstream_url="",
        upstream_api_key="",
        upstream_protocol="openai",
    )
    store = GatewayStore(str(tmp_path / "gateway.db"))
    service = RoomNewspaperService(cfg, store)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run_check():
        try:
            return await service._quality_check(client, [_item(1, "hacker_news", "interest")])
        finally:
            await client.aclose()

    dropped_ids, detail = asyncio.run(run_check())

    assert dropped_ids == {"candidate-1"}
    assert detail["used"] is True
    assert detail["model"] == "small-editor"


def test_generate_draft_excludes_entries_without_real_feed_summaries(tmp_path):
    store = GatewayStore(str(tmp_path / "gateway.db"))
    cfg = SimpleNamespace(room_newspaper_qa_enabled=False)
    service = RoomNewspaperService(cfg, store)
    candidates = [
        _item(index, "arxiv_ai", "interest")
        for index in range(8)
    ] + [
        _item(index, "nasa_apod", "random")
        for index in range(8, 12)
    ]
    candidates.append(NewspaperItem(
        candidate_id="empty-hn",
        source_id="hacker_news",
        source_name="Hacker News",
        bucket="interest",
        title="Headline without feed summary",
        summary="",
        url="https://example.test/empty-hn",
        guid="empty-hn",
        published_at="2026-07-14T00:00:00+00:00",
    ))

    async def fake_fetch(_client):
        return candidates, []

    service.fetch_candidates = fake_fetch  # type: ignore[method-assign]
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))

    async def run_generate():
        try:
            return await service.generate_draft(client=client, rng=random.Random(9), issue_size=5)
        finally:
            await client.aclose()

    issue = asyncio.run(run_generate())

    assert issue["item_count"] == 5
    assert all(item["summary"] for item in issue["items"])
    assert "https://example.test/empty-hn" not in store.used_room_newspaper_urls()
