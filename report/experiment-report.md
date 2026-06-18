# Experiment 2 Report: Conversational AI News Intelligence Agent

## 1. Project Overview

This project implements a CLI-only AI news intelligence agent. The user starts the application with `ai-news start`; DeepSeek first guides the user to provide the topic, time range, and number of news items, then plans MCP tool calls. The local MCP server returns real external context, and the assistant prints a Chinese numbered news answer directly in the conversation.

The agent does not rely on the LLM's base knowledge. It gathers context through tools before answering.

## 2. Architecture

The system has three layers:

- CLI layer: `ai-news start`, `ai-news history`, `ai-news sources`, `ai-news doctor`
- Agent orchestration layer: runs the intake conversation, starts an MCP client, sends tool schemas to DeepSeek, executes model-requested tools, records JSONL cache
- MCP tools layer: RSS fetching, arXiv search, Hacker News search, article extraction, dedup/ranking

## 3. Tool Skills

Implemented MCP skills:

- `fetch_rss_items`: reads RSS/Atom feeds
- `search_arxiv_papers`: queries arXiv API
- `search_hackernews_stories`: queries Hacker News Algolia API
- `extract_article_text`: extracts page text with summary fallback
- `deduplicate_and_rank`: merges duplicates and ranks news

## 4. Execution Screenshots

Add screenshots here:

1. `ai-news doctor`
2. `ai-news start`
3. Terminal intake showing the assistant asking for missing time range or quantity
4. Terminal output showing the numbered news answer and `ai-news history --session <session> --limit 20`

## 5. Reflection

A specific technical hurdle was allowing the model to plan MCP tool usage without forcing it to copy large JSON arrays between tools. The initial design exposed `extract_article_text(items)` and `deduplicate_and_rank(items)` directly, but a model would need to paste prior tool results into later tool calls.

The solution was to keep an accumulated news state inside the Agent. The system prompt tells the model it may omit `items` for extraction and ranking. When omitted, the Agent automatically fills the argument with the latest collected or extracted news. A separate intake stage was added so the model can ask for missing user requirements before any MCP tools are called.
