from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from ai_news import tools

mcp = FastMCP("daily-ai-news")


@mcp.tool()
def fetch_rss_items(
    sources: list[str] | None = None,
    hours: int = 24,
    limit_per_source: int = 10,
) -> list[dict]:
    return tools.fetch_rss_items(sources=sources, hours=hours, limit_per_source=limit_per_source)


@mcp.tool()
def search_arxiv_papers(
    categories: list[str] | None = None,
    hours: int = 24,
    max_results: int = 10,
) -> list[dict]:
    return tools.search_arxiv_papers(categories=categories, hours=hours, max_results=max_results)


@mcp.tool()
def search_hackernews_stories(
    terms: list[str] | None = None,
    hours: int = 24,
    max_results: int = 10,
) -> list[dict]:
    return tools.search_hackernews_stories(terms=terms, hours=hours, max_results=max_results)


@mcp.tool()
def extract_article_text(
    items: list[dict],
    max_chars: int = 3000,
    timeout_seconds: int = 12,
) -> list[dict]:
    return tools.extract_article_text(items=items, max_chars=max_chars, timeout_seconds=timeout_seconds)


@mcp.tool()
def deduplicate_and_rank(
    items: list[dict],
    top_k: int = 8,
) -> list[dict]:
    return tools.deduplicate_and_rank(items=items, top_k=top_k)


def main() -> None:
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
