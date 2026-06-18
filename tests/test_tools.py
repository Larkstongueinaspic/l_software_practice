from __future__ import annotations

import feedparser
import httpx

from ai_news import tools


RSS_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>AI Feed</title>
    <item>
      <title>OpenAI releases a new agent SDK</title>
      <link>https://example.com/openai-agent</link>
      <pubDate>Wed, 17 Jun 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[An AI agent development update.]]></description>
    </item>
  </channel>
</rss>
"""

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2606.00001v1</id>
    <updated>2026-06-17T09:00:00Z</updated>
    <published>2026-06-17T09:00:00Z</published>
    <title>Efficient Reasoning for Large Language Models</title>
    <summary>We study reasoning in LLM agents.</summary>
    <category term="cs.AI" />
    <link href="http://arxiv.org/abs/2606.00001v1" rel="alternate" type="text/html" />
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200, json_data: dict | None = None, headers: dict | None = None):
        self.text = text
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {"content-type": "text/html"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self) -> dict:
        return self._json_data or {}


def test_fetch_rss_items_parses_feed(monkeypatch):
    real_parse = feedparser.parse

    def fake_parse(_source):
        return real_parse(RSS_XML)

    monkeypatch.setattr(tools.feedparser, "parse", fake_parse)
    items = tools.fetch_rss_items(["https://example.com/rss.xml"], hours=24, limit_per_source=5)

    assert len(items) == 1
    assert items[0]["title"] == "OpenAI releases a new agent SDK"
    assert items[0]["url"] == "https://example.com/openai-agent"
    assert "agent" in items[0]["tags"]


def test_search_arxiv_papers_parses_atom(monkeypatch):
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: FakeResponse(text=ARXIV_XML))

    items = tools.search_arxiv_papers(hours=24, max_results=5)

    assert len(items) == 1
    assert items[0]["source"] == "arXiv"
    assert items[0]["url"] == "http://arxiv.org/abs/2606.00001v1"
    assert "cs.AI" in items[0]["tags"]


def test_search_hackernews_stories_parses_json(monkeypatch):
    payload = {
        "hits": [
            {
                "objectID": "123",
                "title": "DeepSeek MCP agent demo",
                "url": "https://example.com/deepseek-mcp",
                "created_at": "2026-06-17T08:00:00Z",
                "points": 42,
                "num_comments": 7,
            }
        ]
    }
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: FakeResponse(json_data=payload))

    items = tools.search_hackernews_stories(terms=["DeepSeek"], hours=24, max_results=5)

    assert len(items) == 1
    assert items[0]["source"] == "Hacker News"
    assert "Points: 42" in items[0]["summary"]


def test_extract_article_text_falls_back_to_summary(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(tools.httpx, "get", raise_timeout)
    item = {
        "id": "x",
        "title": "AI story",
        "url": "https://example.com/story",
        "source": "Example",
        "published_at": "2026-06-17T08:00:00+00:00",
        "summary": "Fallback summary",
        "raw_text": "",
        "tags": [],
    }

    enriched = tools.extract_article_text([item])

    assert enriched[0]["raw_text"] == "Fallback summary"


def test_deduplicate_and_rank_merges_duplicate_titles():
    base = {
        "source": "Example",
        "published_at": "2026-06-17T08:00:00+00:00",
        "summary": "AI model news",
        "raw_text": "AI model news",
        "tags": ["ai"],
    }
    items = [
        {"id": "1", "title": "OpenAI launches new model", "url": "https://example.com/a?utm_source=x", **base},
        {"id": "2", "title": "OpenAI launches new model", "url": "https://example.com/a", **base},
        {"id": "3", "title": "arXiv paper on LLM agents", "url": "https://example.com/b", **base},
    ]

    ranked = tools.deduplicate_and_rank(items, top_k=8)

    assert len(ranked) == 2
    assert ranked[0]["score"] >= ranked[1]["score"]

