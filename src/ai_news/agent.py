from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ai_news.config import LOG_FILE, LOGS_DIR
from ai_news.deepseek_client import DeepSeekClient, generate_mock_digest
from ai_news.models import ToolTrace
from ai_news.tools import isoformat, utc_now


def configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def compact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, list):
            compact[key] = {"count": len(value)}
        elif isinstance(value, dict):
            compact[key] = {"keys": sorted(value.keys())}
        elif isinstance(value, str) and len(value) > 160:
            compact[key] = value[:157] + "..."
        else:
            compact[key] = value
    return compact


def result_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        if "item_count" in value:
            return int(value["item_count"])
        if "items" in value and isinstance(value["items"], list):
            return len(value["items"])
    return None


def decode_mcp_result(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    content = getattr(result, "content", None) or []
    if not content:
        return None
    if len(content) == 1:
        text = getattr(content[0], "text", None)
        if text is None:
            return content[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    values: list[Any] = []
    for part in content:
        text = getattr(part, "text", None)
        if text is None:
            values.append(part)
            continue
        try:
            values.append(json.loads(text))
        except json.JSONDecodeError:
            values.append(text)
    return values


class ToolCaller:
    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self.trace: list[dict[str, Any]] = []

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        optional: bool = False,
    ) -> Any:
        arguments = arguments or {}
        started = time.perf_counter()
        timestamp = isoformat(utc_now())
        logging.info("calling MCP tool %s args=%s", tool, compact_arguments(arguments))
        try:
            raw_result = await self.session.call_tool(tool, arguments=arguments)
            decoded = decode_mcp_result(raw_result)
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            self.trace.append(
                ToolTrace(
                    tool=tool,
                    arguments=compact_arguments(arguments),
                    timestamp=timestamp,
                    duration_ms=duration_ms,
                    result_count=result_count(decoded),
                ).model_dump()
            )
            logging.info("MCP tool %s finished duration_ms=%s count=%s", tool, duration_ms, result_count(decoded))
            return decoded
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            self.trace.append(
                ToolTrace(
                    tool=tool,
                    arguments=compact_arguments(arguments),
                    timestamp=timestamp,
                    duration_ms=duration_ms,
                    error=str(exc),
                ).model_dump()
            )
            logging.exception("MCP tool %s failed", tool)
            if optional:
                return []
            raise


async def run_digest(
    *,
    hours: int = 24,
    top_k: int = 8,
    mock_llm: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    configure_logging()
    server = StdioServerParameters(command=sys.executable, args=["-m", "ai_news.mcp_server"])

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            caller = ToolCaller(session)

            rss_items = await caller.call(
                "fetch_rss_items",
                {"hours": hours, "limit_per_source": max(8, top_k)},
                optional=True,
            )
            arxiv_items = await caller.call(
                "search_arxiv_papers",
                {"hours": hours, "max_results": max(8, top_k)},
                optional=True,
            )
            hn_items = await caller.call(
                "search_hackernews_stories",
                {"hours": hours, "max_results": max(8, top_k)},
                optional=True,
            )

            combined = (rss_items or []) + (arxiv_items or []) + (hn_items or [])
            if not combined:
                raise RuntimeError("No news items were collected from MCP tools.")

            extraction_limit = min(len(combined), max(top_k * 4, 16))
            enriched = await caller.call(
                "extract_article_text",
                {"items": combined[:extraction_limit], "max_chars": 2200, "timeout_seconds": 10},
            )
            ranked = await caller.call(
                "deduplicate_and_rank",
                {"items": enriched, "top_k": top_k},
            )
            if not ranked:
                raise RuntimeError("No ranked news items were produced.")

            if mock_llm:
                markdown = generate_mock_digest(ranked, hours)
            else:
                markdown = await asyncio.to_thread(DeepSeekClient().generate_digest, ranked, hours)

            write_args = {
                "markdown": markdown,
                "items": ranked,
                "trace": caller.trace,
                "output_dir": str(output_dir) if output_dir else None,
            }
            write_result = await caller.call("write_digest", write_args)
            return {
                "markdown": markdown,
                "ranked_items": ranked,
                "trace": caller.trace,
                "write_result": write_result,
            }
