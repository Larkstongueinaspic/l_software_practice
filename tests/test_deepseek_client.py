from __future__ import annotations

from types import SimpleNamespace

from ai_news.deepseek_client import (
    INTAKE_TOOL_SCHEMAS,
    NEWS_TOOL_SCHEMAS,
    generate_mock_chat,
    news_request_from_tool_call,
)


def test_tool_schema_contains_all_news_tools():
    names = {tool["function"]["name"] for tool in NEWS_TOOL_SCHEMAS}

    assert names == {
        "fetch_rss_items",
        "search_arxiv_papers",
        "search_hackernews_stories",
        "extract_article_text",
        "deduplicate_and_rank",
    }


def test_intake_tool_schema_contains_submit_news_request():
    names = {tool["function"]["name"] for tool in INTAKE_TOOL_SCHEMAS}

    assert names == {"submit_news_request"}


def test_news_request_from_tool_call_parses_arguments():
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="submit_news_request",
            arguments='{"question":"AI模型发布","hours":24,"top_k":5}',
        ),
    )

    request = news_request_from_tool_call(tool_call)

    assert request is not None
    assert request.question == "AI模型发布"
    assert request.hours == 24
    assert request.top_k == 5


def test_news_request_from_tool_call_clamps_bounds():
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="submit_news_request",
            arguments='{"question":"AI新闻","hours":9999,"top_k":99}',
        ),
    )

    request = news_request_from_tool_call(tool_call)

    assert request is not None
    assert request.hours == 24 * 30
    assert request.top_k == 20


def test_mock_chat_uses_numbered_plain_text_without_markdown_heading():
    item = {
        "id": "1",
        "title": "AI agent news",
        "url": "https://example.com",
        "source": "Example",
        "published_at": "2026-06-18T00:00:00+00:00",
        "summary": "A useful AI agent update.",
        "raw_text": "A useful AI agent update.",
        "tags": ["ai"],
        "score": 3.0,
        "reason": "source=Example",
    }

    output = generate_mock_chat([item], 24, "今天AI新闻有哪些？")

    assert "#" not in output
    assert "1. AI agent news" in output
