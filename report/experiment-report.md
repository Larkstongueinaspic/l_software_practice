# Experiment 2 Report: Daily AI News Intelligence Agent

## 1. Project Overview

This project implements a CLI-only AI news intelligence agent. It collects recent AI-related news from external sources, uses a local MCP server to expose tool skills, and calls the DeepSeek API to generate a Chinese daily digest.

The agent does not rely on the LLM's base knowledge. It first gathers structured context through tools, then asks DeepSeek to summarize only those tool results.

## 2. Architecture

The system has three layers:

- CLI layer: `ai-news digest`, `ai-news sources`, `ai-news doctor`, `ai-news install-cron`
- Agent orchestration layer: starts an MCP client, calls tools, records trace, invokes DeepSeek
- MCP tools layer: RSS fetching, arXiv search, Hacker News search, article extraction, dedup/ranking, file writing

## 3. Tool Skills

Implemented skills:

- `fetch_rss_items`: reads RSS/Atom feeds
- `search_arxiv_papers`: queries arXiv API
- `search_hackernews_stories`: queries Hacker News Algolia API
- `extract_article_text`: extracts page text with summary fallback
- `deduplicate_and_rank`: merges duplicates and ranks news
- `write_digest`: writes Markdown digest and JSON trace

## 4. Execution Screenshots

Add screenshots here:

1. `ai-news doctor`
2. `ai-news digest --hours 24 --top-k 8`
3. Generated Markdown digest
4. Generated JSON trace showing MCP tool calls

## 5. Reflection

A specific technical hurdle was making the MCP client robust against response shape differences. Depending on SDK behavior, tool results may come back as structured content or as JSON text content. The initial plan assumed one fixed response format, which would make the CLI fragile.

The solution was to implement a defensive decoder in the agent layer. It first checks for structured content, then falls back to parsing JSON text, and finally returns raw text if JSON parsing fails. This kept the orchestration loop stable while preserving the MCP integration required by the experiment.

Another issue was webpage extraction reliability. Some article pages are slow, blocked, or return non-article HTML. The extractor now uses RSS/API summaries as fallback context, so the daily digest can still be generated even when article extraction fails.
