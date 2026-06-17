from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from ai_news.config import (
    AI_KEYWORDS,
    DEFAULT_ARXIV_CATEGORIES,
    DEFAULT_HN_TERMS,
    DEFAULT_RSS_SOURCES,
    DIGESTS_DIR,
    TRACES_DIR,
)
from ai_news.models import NewsItem, RankedNewsItem


USER_AGENT = "daily-ai-news-agent/0.1 (+https://example.local)"


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = date_parser.parse(value)
        except (ValueError, TypeError, OverflowError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def isoformat(dt: datetime | None) -> str:
    return (dt or utc_now()).astimezone(UTC).isoformat()


def stable_id(*parts: str) -> str:
    payload = "|".join(part.strip() for part in parts if part)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" "))).strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "fbclid", "gclid"))
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urlencode(filtered_query),
            "",
        )
    )


def keyword_tags(text: str) -> list[str]:
    lower = text.lower()
    tags = [keyword for keyword in AI_KEYWORDS if keyword in lower]
    return list(dict.fromkeys(tags))[:8]


def within_hours(published_at: datetime | None, hours: int) -> bool:
    if not published_at:
        return True
    return published_at >= utc_now() - timedelta(hours=hours)


def fetch_rss_items(
    sources: list[str] | None = None,
    hours: int = 24,
    limit_per_source: int = 10,
) -> list[dict[str, Any]]:
    """Fetch structured items from RSS or Atom feeds."""
    items: list[NewsItem] = []
    for source_url in sources or DEFAULT_RSS_SOURCES:
        parsed_feed = feedparser.parse(source_url)
        feed_title = strip_html(parsed_feed.feed.get("title", "")) if parsed_feed.feed else ""
        source_name = feed_title or urlparse(source_url).netloc or source_url
        source_count = 0

        for entry in parsed_feed.entries:
            published = parse_datetime(
                entry.get("published_parsed")
                or entry.get("updated_parsed")
                or entry.get("published")
                or entry.get("updated")
            )
            if not within_hours(published, hours):
                continue

            title = strip_html(entry.get("title", ""))
            url = entry.get("link", "") or source_url
            summary = strip_html(entry.get("summary") or entry.get("description") or "")
            text_for_tags = f"{title} {summary}"
            item = NewsItem(
                id=stable_id(source_name, url, title),
                title=title or "(untitled)",
                url=url,
                source=source_name,
                published_at=isoformat(published),
                summary=summary,
                raw_text=summary,
                tags=keyword_tags(text_for_tags),
            )
            items.append(item)
            source_count += 1
            if source_count >= limit_per_source:
                break

    return [item.model_dump() for item in items]


def search_arxiv_papers(
    categories: list[str] | None = None,
    hours: int = 24,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Search recent arXiv AI papers."""
    categories = categories or DEFAULT_ARXIV_CATEGORIES
    search_query = " OR ".join(f"cat:{category}" for category in categories)
    response = httpx.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()

    root = ElementTree.fromstring(response.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[NewsItem] = []
    for entry in root.findall("atom:entry", ns):
        title = re.sub(r"\s+", " ", (entry.findtext("atom:title", default="", namespaces=ns))).strip()
        summary = re.sub(r"\s+", " ", (entry.findtext("atom:summary", default="", namespaces=ns))).strip()
        published = parse_datetime(entry.findtext("atom:published", default="", namespaces=ns))
        if not within_hours(published, hours):
            continue

        entry_id = entry.findtext("atom:id", default="", namespaces=ns)
        link = entry_id
        for link_el in entry.findall("atom:link", ns):
            if link_el.attrib.get("rel") == "alternate":
                link = link_el.attrib.get("href", entry_id)
                break
        tags = [cat.attrib.get("term", "") for cat in entry.findall("atom:category", ns)]
        item = NewsItem(
            id=stable_id("arxiv", link, title),
            title=title or "(untitled arXiv paper)",
            url=link,
            source="arXiv",
            published_at=isoformat(published),
            summary=summary,
            raw_text=summary,
            tags=[tag for tag in tags if tag] + keyword_tags(f"{title} {summary}"),
        )
        items.append(item)

    return [item.model_dump() for item in items[:max_results]]


def search_hackernews_stories(
    terms: list[str] | None = None,
    hours: int = 24,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Search recent Hacker News stories through the public Algolia API."""
    terms = terms or DEFAULT_HN_TERMS
    since_ts = int((utc_now() - timedelta(hours=hours)).timestamp())
    collected: dict[str, NewsItem] = {}

    for term in terms:
        response = httpx.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": term,
                "tags": "story",
                "numericFilters": f"created_at_i>{since_ts}",
                "hitsPerPage": max_results,
            },
            timeout=20,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        for hit in response.json().get("hits", []):
            title = strip_html(hit.get("title") or hit.get("story_title") or "")
            object_id = str(hit.get("objectID", ""))
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            published = parse_datetime(hit.get("created_at"))
            points = hit.get("points") or 0
            comments = hit.get("num_comments") or 0
            summary = f"Hacker News discussion. Points: {points}. Comments: {comments}. Matched term: {term}."
            item = NewsItem(
                id=stable_id("hn", object_id or url, title),
                title=title or "(untitled HN story)",
                url=url,
                source="Hacker News",
                published_at=isoformat(published),
                summary=summary,
                raw_text=strip_html(hit.get("story_text") or "") or summary,
                tags=list(dict.fromkeys([term.lower(), "hacker news"] + keyword_tags(title))),
            )
            collected[item.id] = item

    sorted_items = sorted(
        collected.values(),
        key=lambda item: parse_datetime(item.published_at) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return [item.model_dump() for item in sorted_items[:max_results]]


def extract_article_text(
    items: list[dict[str, Any]],
    max_chars: int = 3000,
    timeout_seconds: int = 12,
) -> list[dict[str, Any]]:
    """Fetch article pages and extract readable text, falling back to existing summaries."""
    enriched: list[NewsItem] = []
    headers = {"User-Agent": USER_AGENT}

    for raw_item in items:
        item = NewsItem.model_validate(raw_item)
        extracted = ""
        parsed_url = urlparse(item.url)
        should_fetch = parsed_url.scheme in {"http", "https"} and "arxiv.org/abs/" not in item.url

        if should_fetch:
            try:
                response = httpx.get(item.url, timeout=timeout_seconds, follow_redirects=True, headers=headers)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "html" in content_type or not content_type:
                    soup = BeautifulSoup(response.text, "html.parser")
                    for selector in ["script", "style", "noscript", "nav", "header", "footer", "form"]:
                        for element in soup.select(selector):
                            element.decompose()
                    paragraphs = [
                        re.sub(r"\s+", " ", paragraph.get_text(" ")).strip()
                        for paragraph in soup.find_all(["p", "li"])
                    ]
                    useful = [paragraph for paragraph in paragraphs if len(paragraph) >= 45]
                    extracted = "\n".join(useful)
            except Exception:
                extracted = ""

        fallback = item.raw_text or item.summary
        item.raw_text = (extracted or fallback or item.title)[:max_chars].strip()
        enriched.append(item)

    return [item.model_dump() for item in enriched]


def deduplicate_and_rank(
    items: list[dict[str, Any]],
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Deduplicate items and rank them with simple transparent heuristics."""
    unique: list[NewsItem] = []
    seen_urls: set[str] = set()

    for raw_item in items:
        item = NewsItem.model_validate(raw_item)
        normalized = normalize_url(item.url)
        if normalized in seen_urls:
            continue
        duplicate_title = any(
            SequenceMatcher(None, item.title.lower(), existing.title.lower()).ratio() > 0.88
            for existing in unique
        )
        if duplicate_title:
            continue
        seen_urls.add(normalized)
        unique.append(item)

    ranked: list[RankedNewsItem] = []
    for item in unique:
        source_weight = {
            "arXiv": 2.0,
            "Hacker News": 1.2,
        }.get(item.source, 1.5)
        if "openai" in item.source.lower() or "github" in item.source.lower():
            source_weight += 0.6

        published = parse_datetime(item.published_at)
        age_hours = max((utc_now() - published).total_seconds() / 3600, 0) if published else 24
        recency_score = max(0.0, 2.0 - age_hours / 24)
        keyword_score = min(len(keyword_tags(f"{item.title} {item.summary} {item.raw_text}")) * 0.25, 1.5)
        text_score = min(len(item.raw_text) / 1500, 1.0)
        score = round(source_weight + recency_score + keyword_score + text_score, 3)
        reason = (
            f"source={item.source}; recency={recency_score:.2f}; "
            f"keywords={keyword_score:.2f}; content={text_score:.2f}"
        )
        ranked.append(RankedNewsItem(**item.model_dump(), score=score, reason=reason))

    ranked.sort(key=lambda item: item.score, reverse=True)
    return [item.model_dump() for item in ranked[:top_k]]


def write_digest(
    markdown: str,
    items: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    date: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Write the final Markdown digest and JSON execution trace."""
    date_str = date or utc_now().date().isoformat()
    output_root = Path(output_dir) if output_dir else DIGESTS_DIR.parent
    digest_dir = output_root / "digests"
    trace_dir = output_root / "traces"
    digest_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)

    digest_path = digest_dir / f"{date_str}-ai-news.md"
    trace_path = trace_dir / f"{date_str}-run.json"
    trace_with_write = trace + [
        {
            "tool": "write_digest",
            "arguments": {
                "markdown": {"chars": len(markdown)},
                "items": {"count": len(items)},
                "output_dir": str(output_root),
            },
            "timestamp": isoformat(utc_now()),
            "duration_ms": 0.0,
            "result_count": len(items),
            "error": None,
        }
    ]
    digest_path.write_text(markdown.strip() + "\n", encoding="utf-8")
    trace_path.write_text(
        json.dumps(
            {
                "date": date_str,
                "generated_at": isoformat(utc_now()),
                "item_count": len(items),
                "items": items,
                "trace": trace_with_write,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "digest_path": str(digest_path),
        "trace_path": str(trace_path),
        "item_count": len(items),
    }
