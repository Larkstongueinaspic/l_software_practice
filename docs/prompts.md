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

## Prompt 5 - Conversational Tool Calling

> Replace the Markdown daily digest with a single-turn CLI chat command. Let DeepSeek plan OpenAI-compatible tool calls, execute local MCP tools, return tool results to the model, print a numbered Chinese answer in the terminal, and cache user/tool/assistant events as JSONL.

Result: added `ai-news chat`, `ai-news history`, DeepSeek tool schemas, a tool-calling loop, and `cache/conversations/{session}.jsonl`.

## Prompt 6 - Interactive Intake

> Make the app more user-friendly: the command should only enter the program. DeepSeek should guide the user in the CLI, collect topic, time range, and news count, then autonomously call the MCP server and answer.

Result: added `ai-news start`, an intake system prompt, `submit_news_request`, continuous CLI conversation, and intake JSONL cache events.

## Technical Hurdles Observed

- MCP tool responses may be returned as structured content or JSON text depending on SDK behavior, so the client includes a defensive decoder.
- Some websites block or delay full article extraction. The extractor falls back to feed/API summaries to keep the chat pipeline reliable.
- Passing entire tool results back into later tool calls can be expensive and brittle. The Agent now keeps accumulated news state and fills omitted `items` for extraction/ranking tools.
- The app now separates requirement intake from tool execution, so missing time range or quantity triggers a model follow-up instead of an accidental MCP request.
- News source recency varies by day. The HN and arXiv tools are included to reduce the chance of an empty daily run.
