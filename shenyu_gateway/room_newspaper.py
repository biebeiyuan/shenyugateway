from __future__ import annotations

import asyncio
import hashlib
import html
import json
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .runtime import logger
from .upstream_adapter import _openai_to_anthropic
from .upstream_client import chat_url_for, detect_protocol_for


@dataclass(frozen=True)
class FeedSource:
    source_id: str
    name: str
    url: str
    bucket: str
    weight: float = 1.0
    archive: bool = False


@dataclass(frozen=True)
class NewspaperItem:
    candidate_id: str
    source_id: str
    source_name: str
    bucket: str
    title: str
    summary: str
    url: str
    guid: str
    published_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


FEED_SOURCES: tuple[FeedSource, ...] = (
    FeedSource("hacker_news", "Hacker News", "https://hnrss.org/frontpage", "interest", 2.2),
    FeedSource("lobsters", "Lobsters", "https://lobste.rs/rss", "interest", 1.3),
    FeedSource("arxiv_ai", "arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI", "interest", 1.2),
    FeedSource("arxiv_cl", "arXiv cs.CL", "https://rss.arxiv.org/rss/cs.CL", "interest", 1.2),
    FeedSource("quanta", "Quanta Magazine", "https://www.quantamagazine.org/feed/", "interest"),
    FeedSource("aeon", "Aeon", "https://aeon.co/feed.rss", "interest", 0.9),
    FeedSource("nautilus", "Nautilus", "https://nautil.us/feed/", "interest", 0.9),
    FeedSource("marginalian", "The Marginalian", "https://www.themarginalian.org/feed/", "interest", 0.9),
    FeedSource("hakai", "Hakai Magazine", "https://hakaimagazine.com/feed/", "random", 0.7, archive=True),
    FeedSource(
        "sciencedaily_animals",
        "ScienceDaily Animals",
        "https://www.sciencedaily.com/rss/plants_animals/animals.xml",
        "random",
        1.4,
    ),
    FeedSource("nasa_apod", "NASA APOD", "https://apod.nasa.gov/apod.rss", "random"),
)


_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_WORDPRESS_BOILERPLATE = re.compile(
    r"\s*The post .+? (?:first appeared|appeared first|appeared) on .+?\s*\.?\s*$",
    re.IGNORECASE,
)
_ARXIV_PREFIX = re.compile(r"^arXiv:\S+\s+Announce Type:\s*\w+\s+Abstract:\s*", re.IGNORECASE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'([])|(?<=[。！？])")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.image_alts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            self._ignored_depth += 1
            return
        if lowered in {"br", "p", "li", "div"}:
            self.parts.append("\n")
        if lowered == "img":
            alt = dict(attrs).get("alt")
            if alt and alt.strip():
                self.image_alts.append(alt.strip())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif lowered in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def source_catalog() -> list[dict[str, Any]]:
    return [
        {
            "source_id": source.source_id,
            "name": source.name,
            "url": source.url,
            "bucket": source.bucket,
            "archive": source.archive,
        }
        for source in FEED_SOURCES
    ]


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _first_text(node: ET.Element, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if _local_name(child.tag) in wanted and child.text and child.text.strip():
            return child.text.strip()
    return ""


def _entry_link(node: ET.Element) -> str:
    for child in list(node):
        if _local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        rel = str(child.attrib.get("rel") or "alternate").strip().lower()
        if href and rel in {"", "alternate"}:
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def _plain_html(value: str) -> tuple[str, list[str]]:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(value or "")
        parser.close()
    except Exception:
        return " ".join(html.unescape(value or "").split()), []
    text = "\n".join(
        " ".join(line.split())
        for line in "".join(parser.parts).splitlines()
        if " ".join(line.split())
    )
    return html.unescape(text).strip(), parser.image_alts


def _clean_summary(raw: str, source_id: str) -> tuple[str, list[str]]:
    text, image_alts = _plain_html(raw)
    if source_id == "hacker_news" and text.startswith("Article URL:"):
        return "", image_alts
    if source_id == "lobsters" and text.strip().lower() == "comments":
        return "", image_alts
    text = _ARXIV_PREFIX.sub("", text).strip()
    text = _WORDPRESS_BOILERPLATE.sub("", text).strip()
    return text, image_alts


def _summary_excerpt(value: str, max_sentences: int = 3, max_chars: int = 1200) -> str:
    text = " ".join((value or "").split())
    if not text:
        return ""
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    excerpt = " ".join(sentences[:max_sentences]) if sentences else text
    if len(excerpt) <= max_chars:
        return excerpt
    shortened = excerpt[:max_chars].rsplit(" ", 1)[0].strip()
    return shortened or excerpt[:max_chars].strip()


def _canonical_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    query = [
        (key, item_value)
        for key, item_value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
    ]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _normalized_date(raw: str, *, source_id: str, url: str, description: str) -> str:
    value = str(raw or "").strip()
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
    if source_id == "nasa_apod":
        match = re.search(r"(?:ap|S_)(\d{6})", f"{url} {description}")
        if match:
            try:
                parsed = datetime.strptime(match.group(1), "%y%m%d").replace(tzinfo=timezone.utc)
                return parsed.isoformat()
            except ValueError:
                pass
    return ""


def parse_feed(content: bytes, source: FeedSource, *, limit: int = 40) -> list[NewspaperItem]:
    root = ET.fromstring(content)
    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    parsed: list[NewspaperItem] = []
    seen_urls: set[str] = set()
    for entry in entries:
        raw_summary = _first_text(entry, ("description", "summary", "encoded", "content"))
        summary, image_alts = _clean_summary(raw_summary, source.source_id)
        title, _ = _plain_html(_first_text(entry, ("title",)))
        if not title and source.source_id == "nasa_apod":
            title = next((alt for alt in image_alts if alt.strip()), "") or summary
        url = _canonical_url(_entry_link(entry))
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        guid = _first_text(entry, ("guid", "id")) or url
        published_at = _normalized_date(
            _first_text(entry, ("pubdate", "published", "updated", "date")),
            source_id=source.source_id,
            url=url,
            description=raw_summary,
        )
        candidate_id = hashlib.sha256(f"{source.source_id}\n{url}".encode("utf-8")).hexdigest()[:16]
        parsed.append(
            NewspaperItem(
                candidate_id=candidate_id,
                source_id=source.source_id,
                source_name=source.name,
                bucket=source.bucket,
                title=title,
                summary=_summary_excerpt(summary),
                url=url,
                guid=guid,
                published_at=published_at,
            )
        )
        if len(parsed) >= limit:
            break
    return parsed


def _weighted_source_order(
    items: list[NewspaperItem],
    sources: dict[str, FeedSource],
    count: int,
    *,
    rng: random.Random,
    max_per_source: int = 2,
) -> list[NewspaperItem]:
    pools: dict[str, list[NewspaperItem]] = {}
    for item in items:
        pools.setdefault(item.source_id, []).append(item)
    for pool in pools.values():
        rng.shuffle(pool)

    chosen: list[NewspaperItem] = []
    source_counts: dict[str, int] = {}
    while len(chosen) < count:
        available = [
            source_id
            for source_id, pool in pools.items()
            if pool and source_counts.get(source_id, 0) < max_per_source
        ]
        if not available:
            available = [source_id for source_id, pool in pools.items() if pool]
        if not available:
            break
        weights = [max(sources[source_id].weight, 0.01) if source_id in sources else 1.0 for source_id in available]
        source_id = rng.choices(available, weights=weights, k=1)[0]
        chosen.append(pools[source_id].pop())
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
    return chosen


def roll_issue_candidates(
    items: list[NewspaperItem],
    *,
    issue_size: int,
    rng: Optional[random.Random] = None,
    reserve: bool = False,
) -> tuple[list[NewspaperItem], int, int]:
    rng = rng or random.SystemRandom()
    size = max(5, min(int(issue_size), 10))
    interest_count = max(1, min(size - 1, int(size * 0.8 + 0.5)))
    random_count = size - interest_count
    source_map = {source.source_id: source for source in FEED_SOURCES}
    extra_interest = 4 if reserve else 0
    extra_random = 2 if reserve else 0
    interest_items = [item for item in items if item.bucket == "interest"]
    random_items = [item for item in items if item.bucket == "random"]
    chosen_interest = _weighted_source_order(
        interest_items,
        source_map,
        interest_count + extra_interest,
        rng=rng,
    )
    chosen_random = _weighted_source_order(
        random_items,
        source_map,
        random_count + extra_random,
        rng=rng,
    )
    chosen = chosen_interest + chosen_random
    rng.shuffle(chosen)
    return chosen, interest_count, random_count


def _finalize_issue_items(
    candidates: list[NewspaperItem],
    *,
    interest_count: int,
    random_count: int,
    dropped_ids: set[str],
) -> list[NewspaperItem]:
    kept = [item for item in candidates if item.candidate_id not in dropped_ids]
    interest = [item for item in kept if item.bucket == "interest"]
    random_items = [item for item in kept if item.bucket == "random"]
    selected = interest[:interest_count] + random_items[:random_count]
    target = interest_count + random_count
    selected_ids = {item.candidate_id for item in selected}
    if len(selected) < target:
        for item in kept:
            if len(selected) >= target:
                break
            if item.candidate_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item.candidate_id)
    order = {item.candidate_id: index for index, item in enumerate(candidates)}
    selected.sort(key=lambda item: order[item.candidate_id])
    return selected


def _json_object(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(value[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


class RoomNewspaperService:
    def __init__(self, cfg: Any, store: Any, *, sources: Iterable[FeedSource] = FEED_SOURCES) -> None:
        self.cfg = cfg
        self.store = store
        self.sources = tuple(sources)

    def _http_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0),
            "headers": {"user-agent": "ShenyuGatewayRSS/1.0"},
        }
        proxy = str(getattr(self.cfg, "upstream_proxy", "") or "").strip()
        if proxy:
            kwargs["proxy"] = proxy
            kwargs["trust_env"] = False
        else:
            # These are fixed public feed URLs, not user-supplied destinations.
            # WSL commonly needs its mirrored HTTP(S)_PROXY for public network access.
            kwargs["trust_env"] = True
        return httpx.AsyncClient(**kwargs)

    def _quality_http_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(connect=15.0, read=90.0, write=30.0, pool=15.0),
        }
        proxy = str(getattr(self.cfg, "upstream_proxy", "") or "").strip()
        if proxy:
            kwargs["proxy"] = proxy
            kwargs["trust_env"] = False
        else:
            kwargs["trust_env"] = bool(getattr(self.cfg, "upstream_trust_env", False))
        return httpx.AsyncClient(**kwargs)

    async def _fetch_source(
        self,
        client: httpx.AsyncClient,
        source: FeedSource,
    ) -> tuple[list[NewspaperItem], dict[str, Any]]:
        status: dict[str, Any] = {
            "source_id": source.source_id,
            "name": source.name,
            "url": source.url,
            "bucket": source.bucket,
            "archive": source.archive,
            "ok": False,
            "count": 0,
        }
        try:
            response = await client.get(source.url)
            response.raise_for_status()
            items = parse_feed(response.content, source)
            status["ok"] = bool(items)
            status["count"] = len(items)
            status["latest_published_at"] = next((item.published_at for item in items if item.published_at), "")
            if not items:
                status["error"] = "Feed did not contain usable entries."
            return items, status
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            status["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
            logger.warning("[Room newspaper] feed failed source=%s error=%s", source.source_id, exc)
            return [], status

    async def fetch_candidates(
        self,
        client: Optional[httpx.AsyncClient] = None,
    ) -> tuple[list[NewspaperItem], list[dict[str, Any]]]:
        owns_client = client is None
        http_client = client or self._http_client()
        try:
            results = await asyncio.gather(*(self._fetch_source(http_client, source) for source in self.sources))
        finally:
            if owns_client:
                await http_client.aclose()
        items = [item for source_items, _status in results for item in source_items]
        statuses = [status for _source_items, status in results]
        return items, statuses

    def _quality_model_config(self) -> dict[str, str]:
        base_url = str(
            getattr(self.cfg, "room_newspaper_llm_url", "")
            or getattr(self.cfg, "upstream_url", "")
            or ""
        ).strip()
        configured_protocol = str(
            getattr(self.cfg, "room_newspaper_llm_protocol", "")
            or getattr(self.cfg, "upstream_protocol", "auto")
            or "auto"
        )
        return {
            "model": str(getattr(self.cfg, "room_newspaper_llm_model", "") or "").strip(),
            "base_url": base_url,
            "protocol": detect_protocol_for(base_url, configured_protocol),
            "api_key": str(
                getattr(self.cfg, "room_newspaper_llm_api_key", "")
                or getattr(self.cfg, "upstream_api_key", "")
                or ""
            ).strip(),
        }

    async def _quality_check(
        self,
        client: httpx.AsyncClient,
        candidates: list[NewspaperItem],
    ) -> tuple[set[str], dict[str, Any]]:
        if not bool(getattr(self.cfg, "room_newspaper_qa_enabled", False)):
            return set(), {"enabled": False, "used": False, "dropped": []}
        upstream = self._quality_model_config()
        missing = [name for name in ("model", "base_url", "api_key") if not upstream[name]]
        if missing:
            return set(), {
                "enabled": True,
                "used": False,
                "warning": f"Quality model skipped; missing {', '.join(missing)}.",
                "dropped": [],
            }

        candidate_rows = [
            {
                "id": item.candidate_id,
                "source": item.source_name,
                "title": item.title,
                "summary": item.summary,
                "url": item.url,
            }
            for item in candidates
        ]
        prompt = (
            "You are a quality checker for a small RSS newspaper. The source text is immutable. "
            "Only flag entries that are broken, obvious advertising, or duplicates of another candidate. "
            "Do not rewrite, translate, summarize, rank by personal taste, or drop an item merely because its "
            "RSS feed has no summary. Return JSON only as "
            '{"drop":[{"id":"candidate id","reason":"brief reason"}]}. '
            "Use an empty drop array when nothing is clearly defective.\n\nCandidates:\n"
            + json.dumps(candidate_rows, ensure_ascii=False)
        )
        messages = [{"role": "user", "content": prompt}]
        headers = {"content-type": "application/json"}
        if upstream["protocol"] == "anthropic":
            system, anthropic_messages = _openai_to_anthropic(messages)
            payload: dict[str, Any] = {
                "model": upstream["model"],
                "messages": anthropic_messages,
                "max_tokens": 1000,
                "temperature": 0,
            }
            if system:
                payload["system"] = system
            headers["x-api-key"] = upstream["api_key"]
            headers["anthropic-version"] = str(getattr(self.cfg, "upstream_version", "2023-06-01"))
        else:
            payload = {
                "model": upstream["model"],
                "messages": messages,
                "stream": False,
                "max_tokens": 1000,
                "temperature": 0,
            }
            headers["authorization"] = f"Bearer {upstream['api_key']}"
        try:
            response = await client.post(
                chat_url_for(upstream["base_url"], upstream["protocol"]),
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data.get("data"), dict):
                data = data["data"]
            if upstream["protocol"] == "anthropic":
                text = "".join(
                    str(block.get("text") or "")
                    for block in data.get("content") or []
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                choices = data.get("choices") or []
                message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
                content = message.get("content") if isinstance(message, dict) else ""
                if isinstance(content, list):
                    text = "".join(
                        str(block.get("text") or block.get("content") or "")
                        for block in content
                        if isinstance(block, dict)
                    )
                else:
                    text = str(content or "")
            parsed = _json_object(text)
            valid_ids = {item.candidate_id for item in candidates}
            dropped: list[dict[str, str]] = []
            for raw in parsed.get("drop") or []:
                if not isinstance(raw, dict):
                    continue
                candidate_id = str(raw.get("id") or "").strip()
                if candidate_id in valid_ids:
                    dropped.append({"id": candidate_id, "reason": str(raw.get("reason") or "").strip()[:240]})
            return {item["id"] for item in dropped}, {
                "enabled": True,
                "used": True,
                "model": upstream["model"],
                "dropped": dropped,
            }
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("[Room newspaper] quality check failed: %s", exc)
            return set(), {
                "enabled": True,
                "used": False,
                "warning": f"Quality check failed; deterministic issue kept: {str(exc)[:180]}",
                "dropped": [],
            }

    async def generate_draft(
        self,
        *,
        client: Optional[httpx.AsyncClient] = None,
        rng: Optional[random.Random] = None,
        issue_size: Optional[int] = None,
    ) -> dict[str, Any]:
        rng = rng or random.SystemRandom()
        target_size = issue_size if issue_size is not None else rng.randint(5, 10)
        owns_feed_client = client is None
        feed_client = client or self._http_client()
        try:
            candidates, source_status = await self.fetch_candidates(feed_client)
            used_urls = self.store.used_room_newspaper_urls()
            fresh: list[NewspaperItem] = []
            fresh_urls: set[str] = set()
            for item in candidates:
                if item.url in used_urls or item.url in fresh_urls:
                    continue
                fresh.append(item)
                fresh_urls.add(item.url)
            rolled, interest_count, random_count = roll_issue_candidates(
                fresh,
                issue_size=target_size,
                rng=rng,
                reserve=True,
            )
        finally:
            if owns_feed_client:
                await feed_client.aclose()

        owns_quality_client = client is None
        quality_client = client or self._quality_http_client()
        try:
            dropped_ids, qa_detail = await self._quality_check(quality_client, rolled)
        finally:
            if owns_quality_client:
                await quality_client.aclose()
        final_items = _finalize_issue_items(
            rolled,
            interest_count=interest_count,
            random_count=random_count,
            dropped_ids=dropped_ids,
        )
        if len(final_items) < 5 and dropped_ids:
            qa_detail["warning"] = "Quality model dropped too many entries; deterministic issue kept."
            qa_detail["applied"] = False
            final_items = _finalize_issue_items(
                rolled,
                interest_count=interest_count,
                random_count=random_count,
                dropped_ids=set(),
            )
        elif dropped_ids:
            qa_detail["applied"] = True
        if len(final_items) < 5:
            raise ValueError(
                "Not enough unused RSS entries to build an issue. "
                f"Found {len(final_items)} after fetching {len(candidates)} entries."
            )
        return self.store.create_room_newspaper_issue(
            [item.to_dict() for item in final_items],
            source_status=source_status,
            qa_detail=qa_detail,
        )
