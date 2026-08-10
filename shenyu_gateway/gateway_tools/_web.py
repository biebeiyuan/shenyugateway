from __future__ import annotations

"""窗外 tools: web search via Serper (Google SERP) and page reading via Jina Reader.

Model-facing output stays clean: search returns title/url/date/snippet only,
reading returns the page text split into parts. Fetched pages are cached in
process memory for a few minutes so「接着读下一段」does not re-download.
Both calls go to fixed public endpoints (google.serper.dev / r.jina.ai), never
directly to a model-supplied host, so arbitrary-URL fetches stay off this box.
Failures degrade into the standard tool error contract and never raise.
"""

import time
from typing import Any, Optional

import httpx

from shenyu_gateway.runtime import logger

SERPER_SEARCH_URL = "https://google.serper.dev/search"
JINA_READER_URL = "https://r.jina.ai/"
SEARCH_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)
READ_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
WEB_USER_AGENT = "ShenyuGatewayWeb/1.0"
SNIPPET_MAX_CHARS = 320
SEARCH_RESULT_DEFAULT = 5
SEARCH_RESULT_MAX = 8
# Outside failures are a normal operating condition for these two tools, not
# house trouble. The tool_loop decorator only fills `ps` when absent, so these
# replace its "又抓到一个家里的bug" line on the upstream-failure paths; missing keys
# (config) and bad arguments (validation) keep the household wording, because
# those really are ours to fix.
SEARCH_OUTSIDE_PS = "圆儿ps:外面的路没通，不是家里的事，等会儿再试试。"
READ_OUTSIDE_PS = "圆儿ps:外面这页没打开，不是家里的事，换一条看看就好。"

PAGE_PART_CHARS = 15_000
PAGE_MAX_CHARS = 150_000  # 10-14 parts; keeps one huge asset from pinning memory
PAGE_CACHE_TTL_SECONDS = 10 * 60
PAGE_CACHE_MAX_ENTRIES = 16

# url -> (expiry_monotonic, title, text, truncated)
_page_cache: dict[str, tuple[float, str, str, bool]] = {}


def _reset_web_caches() -> None:
    _page_cache.clear()


def _clip(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _split_page_parts(text: str) -> list[str]:
    """Split page text into ~PAGE_PART_CHARS chunks, preferring newline cuts."""
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= PAGE_PART_CHARS:
            parts.append(rest)
            break
        window = rest[:PAGE_PART_CHARS]
        cut = window.rfind("\n", PAGE_PART_CHARS * 3 // 4)
        if cut <= 0:
            cut = PAGE_PART_CHARS
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return parts or [""]


def _parse_jina_page(raw: str) -> tuple[str, str]:
    """Extract (title, body) from an r.jina.ai response.

    With ``x-return-format: text`` Jina returns bare page text, so the usual
    result is ("", whole body). The ``Title:`` / ``URL Source:`` /
    ``Markdown Content:`` envelope is only stripped when the response actually
    opens with it — otherwise a page whose own prose contains the phrase
    "Markdown Content:" would lose everything above it.
    """
    text = raw.strip()
    if not text.startswith(("Title:", "URL Source:")):
        return "", text

    title = ""
    if text.startswith("Title:"):
        first_line, _, _ = text.partition("\n")
        title = first_line[len("Title:"):].strip()
    marker = "Markdown Content:"
    marker_at = text.find(marker)
    if marker_at >= 0:
        text = text[marker_at + len(marker):].lstrip("\n")
    return title, text


class WebToolsMixin:
    def _web_http_client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "timeout": timeout,
            "headers": {"user-agent": WEB_USER_AGENT},
        }
        proxy = str(getattr(self.cfg, "upstream_proxy", "") or "").strip()
        if proxy:
            kwargs["proxy"] = proxy
            kwargs["trust_env"] = False
        else:
            # Fixed public endpoints; WSL commonly needs its mirrored
            # HTTP(S)_PROXY for public network access.
            kwargs["trust_env"] = True
        return httpx.AsyncClient(**kwargs)

    async def web_search(
        self,
        query: Any = "",
        limit: int = SEARCH_RESULT_DEFAULT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> dict:
        api_key = str(getattr(self.cfg, "serper_api_key", "") or "").strip()
        if not api_key:
            return {"ok": False, "error": "Serper API key is not configured.", "error_kind": "config"}
        text = str(query or "").strip()
        if not text:
            return {"ok": False, "error": "query is required.", "error_kind": "validation"}
        try:
            count = max(1, min(int(limit or SEARCH_RESULT_DEFAULT), SEARCH_RESULT_MAX))
        except (TypeError, ValueError):
            count = SEARCH_RESULT_DEFAULT

        own_client = client is None
        http = client or self._web_http_client(SEARCH_TIMEOUT)
        try:
            resp = await http.post(
                SERPER_SEARCH_URL,
                json={"q": text, "gl": "cn", "hl": "zh-cn", "num": count},
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            )
            if resp.status_code in (401, 403):
                # Same reasoning as the Jina branch: a key problem needs an
                # Admin fix, so name it instead of leaving a bare status code.
                return {
                    "ok": False,
                    "error": (
                        "Serper rejected the configured SERPER_API_KEY;"
                        " it may be invalid, revoked, or out of credits."
                    ),
                    "error_kind": "config",
                }
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "error": f"Serper search failed with HTTP {resp.status_code}.",
                    "error_kind": "exception",
                    "ps": SEARCH_OUTSIDE_PS,
                }
            data = resp.json() if resp.content else {}
            organic = data.get("organic") if isinstance(data, dict) else None
            results = []
            for item in organic or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("link") or "").strip()
                title = _clip(item.get("title"), 200)
                if not url or not title:
                    continue
                entry: dict[str, Any] = {
                    "title": title,
                    "url": url,
                    "snippet": _clip(item.get("snippet"), SNIPPET_MAX_CHARS),
                }
                date = str(item.get("date") or "").strip()
                if date:
                    entry["date"] = date
                results.append(entry)
                if len(results) >= count:
                    break
            return {"ok": True, "query": text, "count": len(results), "results": results}
        except httpx.TimeoutException:
            return {
                "ok": False,
                "error": "Web search timed out.",
                "error_kind": "exception",
                "ps": SEARCH_OUTSIDE_PS,
            }
        except Exception as exc:
            logger.warning("[Web] search failed: %s", exc)
            return {
                "ok": False,
                "error": f"Web search failed: {exc}",
                "error_kind": "exception",
                "ps": SEARCH_OUTSIDE_PS,
            }
        finally:
            if own_client:
                await http.aclose()

    async def web_read(
        self,
        url: Any = "",
        part: int = 1,
        client: Optional[httpx.AsyncClient] = None,
    ) -> dict:
        target = str(url or "").strip()
        if not target.startswith(("http://", "https://")):
            return {"ok": False, "error": "url must start with http:// or https://.", "error_kind": "validation"}
        try:
            wanted = max(1, int(part or 1))
        except (TypeError, ValueError):
            wanted = 1

        try:
            title, text, truncated = await self._fetch_page(target, client)
        except httpx.TimeoutException:
            return {
                "ok": False,
                "error": "Page fetch timed out.",
                "error_kind": "exception",
                "ps": READ_OUTSIDE_PS,
            }
        except _ReaderAuthError as exc:
            return {"ok": False, "error": str(exc), "error_kind": "config"}
        except _PageFetchError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "error_kind": "exception",
                "ps": READ_OUTSIDE_PS,
            }
        except Exception as exc:
            logger.warning("[Web] read failed for %s: %s", target, exc)
            return {
                "ok": False,
                "error": f"Page fetch failed: {exc}",
                "error_kind": "exception",
                "ps": READ_OUTSIDE_PS,
            }

        if not text.strip():
            return {
                "ok": False,
                "error": "The page came back empty.",
                "error_kind": "exception",
                "ps": READ_OUTSIDE_PS,
            }
        parts = _split_page_parts(text)
        total = len(parts)
        if wanted > total:
            return {
                "ok": False,
                "error": f"part {wanted} is out of range; this page has {total} part(s).",
                "error_kind": "validation",
            }
        result: dict[str, Any] = {
            "ok": True,
            "url": target,
            "part": wanted,
            "parts": total,
            "content": parts[wanted - 1],
        }
        if title:
            result["title"] = title
        if wanted < total:
            result["rest"] = f"后面还有 {total - wanted} 段没读，part 传 {wanted + 1} 接着读。"
        elif truncated:
            result["rest"] = "这页太长了，后面的没能带回来。"
        return result

    async def _fetch_page(
        self,
        url: str,
        client: Optional[httpx.AsyncClient],
    ) -> tuple[str, str, bool]:
        now = time.monotonic()
        cached = _page_cache.get(url)
        if cached and cached[0] > now:
            return cached[1], cached[2], cached[3]

        # Plain text instead of the default markdown: on real pages the
        # markdown carries far more image/link syntax than prose (a weather
        # page measured 30k chars of markdown for 3k of text). Tool results
        # enter context verbatim and pin into the prompt-cache prefix, so the
        # noise would be paid for over the whole conversation window. Shenyu
        # gets her URLs from search results, not from a page's outbound links.
        headers = {"x-return-format": "text"}
        jina_key = str(getattr(self.cfg, "jina_api_key", "") or "").strip()
        if jina_key:
            headers["Authorization"] = f"Bearer {jina_key}"

        own_client = client is None
        http = client or self._web_http_client(READ_TIMEOUT)
        try:
            resp = await http.get(JINA_READER_URL + url, headers=headers)
            if resp.status_code in (401, 402):
                # Jina refuses anonymous reads from datacenter ASNs and bills
                # exhausted keys the same way; both need an Admin-side fix, so
                # say which one rather than surfacing a bare status code.
                raise _ReaderAuthError(
                    "Jina Reader rejected the request: set JINA_API_KEY in Admin config"
                    " (free key at jina.ai), or check that the configured key still has quota."
                    if not jina_key
                    else "Jina Reader rejected the configured JINA_API_KEY; it may be invalid or out of quota."
                )
            if resp.status_code != 200:
                raise _PageFetchError(f"Page fetch failed with HTTP {resp.status_code}.")
            title, text = _parse_jina_page(resp.text or "")
        finally:
            if own_client:
                await http.aclose()

        truncated = len(text) > PAGE_MAX_CHARS
        if truncated:
            text = text[:PAGE_MAX_CHARS]

        # An empty render is never cached: Jina occasionally returns 200 with
        # nothing extracted for JS-heavy pages, and caching that would make
        # every retry fail for the rest of the TTL instead of refetching.
        if text.strip():
            _page_cache[url] = (now + PAGE_CACHE_TTL_SECONDS, title, text, truncated)
            if len(_page_cache) > PAGE_CACHE_MAX_ENTRIES:
                oldest = min(_page_cache, key=lambda key: _page_cache[key][0])
                _page_cache.pop(oldest, None)
        return title, text, truncated


class _PageFetchError(RuntimeError):
    pass


class _ReaderAuthError(_PageFetchError):
    pass
