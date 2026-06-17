# Vibe Coding Prompt Log

This file records the development prompts used to satisfy the experiment's Vibe Coding Constraint.

## Prompt 1 - Project Skeleton

> Build a Python 3.11 CLI project named Daily AI News Intelligence Agent. Use a src layout, Typer CLI, pytest, and a local MCP server. The CLI must expose `digest`, `sources`, `doctor`, and `install-cron`.

Result: generated the package structure, `pyproject.toml`, CLI entry point, and initial README.

## Prompt 2 - MCP Tools

> Implement MCP tools for RSS/Atom fetching, arXiv search, Hacker News Algolia search, article extraction, deduplication/ranking, and Markdown/JSON trace writing. Use Pydantic models for structured tool data.

Result: generated tool functions and a `FastMCP` server exposing them.

## Prompt 3 - DeepSeek Integration

> Add a DeepSeek API client using the OpenAI-compatible SDK. The system prompt must forbid fabricated news and require Chinese output based only on tool results.

Result: implemented `DeepSeekClient` and a deterministic `--mock-llm` mode for demos.

## Prompt 4 - Tests

> Add pytest coverage for feed parsing, arXiv XML parsing, Hacker News JSON parsing, extraction fallback, deduplication, and file writing.

Result: generated unit tests with mocked network responses and temporary output directories.

## Technical Hurdles Observed

- MCP tool responses may be returned as structured content or JSON text depending on SDK behavior, so the client includes a defensive decoder.
- Some websites block or delay full article extraction. The extractor falls back to feed/API summaries to keep the digest pipeline reliable.
- News source recency varies by day. The HN and arXiv tools are included to reduce the chance of an empty daily run.
