# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from shenyu_gateway.gateway_tools._web import (
    PAGE_MAX_CHARS,
    PAGE_PART_CHARS,
    READ_OUTSIDE_PS,
    SEARCH_OUTSIDE_PS,
    _parse_jina_page,
    _reset_web_caches,
    _split_page_parts,
)
from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.tool_loop import _decorate_tool_error_result


@pytest.fixture(autouse=True)
def clear_caches():
    _reset_web_caches()
    yield
    _reset_web_caches()


def _service(serper_api_key="serper-key", jina_api_key=""):
    cfg = SimpleNamespace(
        serper_api_key=serper_api_key,
        jina_api_key=jina_api_key,
        upstream_proxy="",
        upstream_trust_env=False,
    )
    return GatewayToolService(runtime_config=cfg, supabase=None, store=None)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- search ---------------------------------------------------------------


def test_web_search_requires_configured_key():
    result = asyncio.run(_service(serper_api_key="").web_search(query="邵阳 天气"))
    assert result == {"ok": False, "error": "Serper API key is not configured.", "error_kind": "config"}


def test_web_search_requires_query():
    result = asyncio.run(_service().web_search(query="  "))
    assert result == {"ok": False, "error": "query is required.", "error_kind": "validation"}


def test_web_search_returns_clean_results_only():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("X-API-KEY")
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "searchParameters": {"q": "邵阳 天气", "type": "search"},
                "organic": [
                    {
                        "title": "邵阳天气预报",
                        "link": "https://weather.example.com/shaoyang",
                        "snippet": "未来三天多云转小雨。",
                        "date": "1 天前",
                        "position": 1,
                        "sitelinks": [{"title": "七天预报"}],
                    },
                    {"title": "", "link": "https://skip.example.com"},
                    {
                        "title": "长长的摘要",
                        "link": "https://long.example.com",
                        "snippet": "摘" * 500,
                    },
                ],
                "knowledgeGraph": {"title": "不该出现"},
            },
        )

    async def run():
        async with _client(handler) as client:
            return await _service().web_search(query="邵阳 天气", limit=5, client=client)

    result = asyncio.run(run())
    assert seen["url"] == "https://google.serper.dev/search"
    assert seen["key"] == "serper-key"
    assert seen["payload"]["gl"] == "cn"
    assert seen["payload"]["hl"] == "zh-cn"
    assert seen["payload"]["num"] == 5
    assert result["ok"] is True
    assert result["count"] == 2
    first = result["results"][0]
    assert first == {
        "title": "邵阳天气预报",
        "url": "https://weather.example.com/shaoyang",
        "snippet": "未来三天多云转小雨。",
        "date": "1 天前",
    }
    assert "position" not in first and "sitelinks" not in first
    assert len(result["results"][1]["snippet"]) <= 320
    assert result["results"][1]["snippet"].endswith("…")


def test_web_search_clamps_limit_and_tolerates_garbage():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8"))["num"])
        return httpx.Response(200, json={"organic": []})

    async def run(limit):
        async with _client(handler) as client:
            return await _service().web_search(query="q", limit=limit, client=client)

    assert asyncio.run(run(99))["ok"] is True
    assert asyncio.run(run("not-a-number"))["ok"] is True
    assert seen == [8, 5]


def test_web_search_reports_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    async def run():
        async with _client(handler) as client:
            return await _service().web_search(query="q", client=client)

    result = asyncio.run(run())
    assert result["ok"] is False
    assert result["error"] == "Serper search failed with HTTP 429."
    assert result["error_kind"] == "exception"
    assert result["ps"] == SEARCH_OUTSIDE_PS


@pytest.mark.parametrize("status", [401, 403])
def test_web_search_reports_key_rejection_as_config_error(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="nope")

    async def run():
        async with _client(handler) as client:
            return await _service().web_search(query="q", client=client)

    result = asyncio.run(run())
    assert result["ok"] is False
    assert result["error_kind"] == "config"
    assert "SERPER_API_KEY" in result["error"]


def test_web_search_timeout_degrades_to_error_result():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    async def run():
        async with _client(handler) as client:
            return await _service().web_search(query="q", client=client)

    result = asyncio.run(run())
    assert result["ok"] is False
    assert result["error"] == "Web search timed out."
    assert result["error_kind"] == "exception"
    assert result["ps"] == SEARCH_OUTSIDE_PS


# --- read -----------------------------------------------------------------


def test_web_read_rejects_non_http_url():
    result = asyncio.run(_service().web_read(url="ftp://example.com"))
    assert result["ok"] is False
    assert result["error_kind"] == "validation"


def test_web_read_parses_plain_text_response_and_rest_note():
    """Production shape: `x-return-format: text` returns bare page text."""
    long_text = "\n".join(f"第{i}行，窗外的字。" for i in range(1200))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert str(request.url) == "https://r.jina.ai/https://example.com/a"
        assert "Authorization" not in request.headers
        assert request.headers.get("x-return-format") == "text"
        return httpx.Response(200, text=long_text)

    async def run():
        async with _client(handler) as client:
            first = await _service().web_read(url="https://example.com/a", client=client)
            second = await _service().web_read(url="https://example.com/a", part=2, client=client)
            return first, second

    first, second = asyncio.run(run())
    assert first["ok"] is True
    assert first["part"] == 1
    assert first["parts"] >= 2
    # Bare text carries no envelope, so no title is advertised.
    assert "title" not in first
    assert len(first["content"]) <= PAGE_PART_CHARS
    assert "part 传 2 接着读" in first["rest"]
    assert second["ok"] is True
    assert second["part"] == 2
    assert first["content"] not in second["content"]
    # The page cache keeps 接着读 from re-downloading.
    assert calls["n"] == 1


def test_web_read_still_parses_the_markdown_envelope_if_jina_returns_one():
    body = "Title: 一篇文章\n\nURL Source: https://example.com/a\n\nMarkdown Content:\n正文很短。"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async def run():
        async with _client(handler) as client:
            return await _service().web_read(url="https://example.com/a", client=client)

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["title"] == "一篇文章"
    assert result["content"] == "正文很短。"
    assert result["parts"] == 1
    assert "rest" not in result


def test_web_read_sends_jina_key_when_configured():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, text="正文很短。")

    async def run():
        async with _client(handler) as client:
            return await _service(jina_api_key="jina-key").web_read(
                url="https://example.com/a", client=client
            )

    result = asyncio.run(run())
    assert seen["auth"] == "Bearer jina-key"
    assert result["ok"] is True
    assert result["content"] == "正文很短。"


def test_web_read_rejects_part_out_of_range():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="正文很短。")

    async def run():
        async with _client(handler) as client:
            return await _service().web_read(url="https://example.com/a", part=9, client=client)

    result = asyncio.run(run())
    assert result == {
        "ok": False,
        "error": "part 9 is out of range; this page has 1 part(s).",
        "error_kind": "validation",
    }


@pytest.mark.parametrize("status", [401, 402])
def test_web_read_reports_reader_auth_as_config_error(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"code": status, "name": "AuthenticationRequiredError"})

    async def run(jina_api_key):
        async with _client(handler) as client:
            return await _service(jina_api_key=jina_api_key).web_read(
                url="https://example.com/a", client=client
            )

    anonymous = asyncio.run(run(""))
    assert anonymous["ok"] is False
    assert anonymous["error_kind"] == "config"
    assert "JINA_API_KEY" in anonymous["error"]
    assert "jina.ai" in anonymous["error"]

    _reset_web_caches()

    configured = asyncio.run(run("jina-key"))
    assert configured["error_kind"] == "config"
    assert "invalid or out of quota" in configured["error"]


def test_web_read_reports_http_error_and_empty_page():
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(451, text="blocked")

    async def run_error():
        async with _client(error_handler) as client:
            return await _service().web_read(url="https://example.com/a", client=client)

    result = asyncio.run(run_error())
    assert result["ok"] is False
    assert result["error"] == "Page fetch failed with HTTP 451."
    assert result["error_kind"] == "exception"
    assert result["ps"] == READ_OUTSIDE_PS

    _reset_web_caches()

    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="")

    async def run_empty():
        async with _client(empty_handler) as client:
            return await _service().web_read(url="https://example.com/a", client=client)

    result = asyncio.run(run_empty())
    assert result["ok"] is False
    assert result["error"] == "The page came back empty."
    assert result["error_kind"] == "exception"
    assert result["ps"] == READ_OUTSIDE_PS


def test_outside_failures_do_not_blame_the_house_but_our_own_faults_still_do():
    """A dead link is a normal outside condition, not a bug 沈予 should report."""
    house_line = "圆儿ps:予予你又抓到一个家里的bug^ ^"

    def dead_link(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    async def run_outside():
        async with _client(dead_link) as client:
            return await _service().web_read(url="https://example.com/a", client=client)

    outside = _decorate_tool_error_result(asyncio.run(run_outside()))
    assert outside["ps"] == READ_OUTSIDE_PS
    assert outside["ps"] != house_line

    # A missing key really is ours to fix, so the household wording stays.
    missing_key = _decorate_tool_error_result(
        asyncio.run(_service(serper_api_key="").web_search(query="邵阳"))
    )
    assert missing_key["error_kind"] == "config"
    assert missing_key["ps"] == house_line

    # A malformed call from 沈予 keeps the "check the exposed arguments" wording.
    bad_args = _decorate_tool_error_result(asyncio.run(_service().web_read(url="ftp://x")))
    assert bad_args["error_kind"] == "validation"
    assert "仔细看有没有暴露给你正确的方法" in bad_args["ps"]


def test_web_read_does_not_cache_an_empty_render_so_a_retry_can_succeed():
    """Jina sometimes returns 200 with nothing extracted; that must stay retryable."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text="   ")
        return httpx.Response(200, text="这次读到了正文。")

    async def run():
        async with _client(handler) as client:
            svc = _service()
            first = await svc.web_read(url="https://example.com/a", client=client)
            second = await svc.web_read(url="https://example.com/a", client=client)
            return first, second

    first, second = asyncio.run(run())
    assert first["ok"] is False
    assert first["error"] == "The page came back empty."
    assert second["ok"] is True
    assert second["content"] == "这次读到了正文。"
    assert calls["n"] == 2


def test_web_read_caps_a_huge_page_and_says_so_on_the_last_part():
    huge = "长" * (PAGE_MAX_CHARS + 50_000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=huge)

    async def run():
        async with _client(handler) as client:
            svc = _service()
            first = await svc.web_read(url="https://example.com/a", client=client)
            last = await svc.web_read(url="https://example.com/a", part=first["parts"], client=client)
            return first, last

    first, last = asyncio.run(run())
    assert first["parts"] == PAGE_MAX_CHARS // PAGE_PART_CHARS
    assert last["rest"] == "这页太长了，后面的没能带回来。"


# --- helpers --------------------------------------------------------------


def test_split_page_parts_prefers_newline_cuts_without_dropping_content():
    text = ("a" * 5000 + "\n") + ("b" * 5000 + "\n") + "c" * 5000
    parts = _split_page_parts(text)
    assert parts == ["a" * 5000, "b" * 5000, "c" * 5000]
    assert all(len(part) <= PAGE_PART_CHARS for part in parts)
    assert _split_page_parts("") == [""]
    # A wall of text with no newline still cuts at the hard limit.
    hard = _split_page_parts("x" * (PAGE_PART_CHARS + 10))
    assert [len(part) for part in hard] == [PAGE_PART_CHARS, 10]
    # Only newlines at the cut boundaries are consumed; no other character is
    # dropped and none is duplicated across parts.
    source = "\n".join("行" * 40 for _ in range(400))
    rejoined = "".join(_split_page_parts(source))
    assert rejoined.replace("\n", "") == source.replace("\n", "")


def test_parse_jina_page_only_strips_a_real_envelope():
    envelope = "Title: T\n\nURL Source: u\n\nMarkdown Content:\n正文"
    assert _parse_jina_page(envelope) == ("T", "正文")
    # Bare text is returned whole, even when it mentions the envelope phrase.
    bare = "这篇文章讨论了 Markdown Content: 这个标记本身。"
    assert _parse_jina_page(bare) == ("", bare)
    assert _parse_jina_page("") == ("", "")
