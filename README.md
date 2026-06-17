# Daily AI News Intelligence Agent

A pure CLI Python agent that collects AI news from external sources, runs local MCP tools for context gathering, and uses the DeepSeek API to generate a Chinese daily digest.

## Features

- CLI-only workflow, no frontend.
- Local MCP server exposing separate tools for RSS, arXiv, Hacker News, article extraction, ranking, and digest writing.
- DeepSeek API integration through the OpenAI-compatible endpoint.
- Markdown digest output plus JSON execution trace for experiment screenshots.
- Mock LLM mode for demos without an API key.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
export DEEPSEEK_API_KEY="your-api-key"
```

DeepSeek defaults:

- Base URL: `https://api.deepseek.com`
- Model: `deepseek-v4-flash`

Override with:

```bash
export AI_NEWS_MODEL="deepseek-v4-pro"
```

## CLI

```bash
ai-news doctor
ai-news sources
ai-news digest --hours 24 --top-k 8
ai-news digest --hours 24 --top-k 8 --mock-llm
ai-news install-cron --time 08:00
```

Generated files:

```text
outputs/digests/YYYY-MM-DD-ai-news.md
outputs/traces/YYYY-MM-DD-run.json
logs/agent.log
```

## Experiment Notes

This project satisfies the BYOA experiment requirements by using:

- More than two distinct tools: RSS fetch, arXiv search, Hacker News search, article extraction, dedup/ranking, digest writing.
- MCP as the context integration layer between the CLI agent and local tools.
- AI-assisted development records in `docs/prompts.md`.

Run tests:

```bash
pytest
```
