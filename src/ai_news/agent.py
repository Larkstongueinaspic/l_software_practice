from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ai_news.config import LOG_FILE, LOGS_DIR
from ai_news.conversation_cache import ConversationCache
from ai_news.deepseek_client import (
    INTAKE_SYSTEM_PROMPT,
    INTAKE_TOOL_SCHEMAS,
    NEWS_TOOL_SCHEMAS,
    SYSTEM_PROMPT,
    DeepSeekClient,
    assistant_message_to_dict,
    generate_mock_chat,
    news_request_from_tool_call,
    tool_call_to_dict,
)
from ai_news.models import NewsRequest, ToolTrace
from ai_news.tools import isoformat, utc_now

SOURCE_TOOLS = {"fetch_rss_items", "search_arxiv_papers", "search_hackernews_stories"}
NEWS_TOOLS = SOURCE_TOOLS | {"extract_article_text", "deduplicate_and_rank"}


def configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
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


class NewsToolState:
    def __init__(self, hours: int, top_k: int) -> None:
        self.hours = hours
        self.top_k = top_k
        self.collected_items: list[dict[str, Any]] = []
        self.current_items: list[dict[str, Any]] = []
        self.ranked_items: list[dict[str, Any]] = []

    def resolve_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(arguments)
        if tool_name == "fetch_rss_items":
            resolved.setdefault("hours", self.hours)
            resolved.setdefault("limit_per_source", max(8, self.top_k))
        elif tool_name == "search_arxiv_papers":
            resolved.setdefault("hours", self.hours)
            resolved.setdefault("max_results", max(8, self.top_k))
        elif tool_name == "search_hackernews_stories":
            resolved.setdefault("hours", self.hours)
            resolved.setdefault("max_results", max(8, self.top_k))
        elif tool_name == "extract_article_text":
            if not resolved.get("items"):
                resolved["items"] = (self.current_items or self.collected_items)[: max(self.top_k * 4, 16)]
            resolved.setdefault("max_chars", 2200)
            resolved.setdefault("timeout_seconds", 10)
        elif tool_name == "deduplicate_and_rank":
            if not resolved.get("items"):
                resolved["items"] = self.current_items or self.collected_items
            resolved.setdefault("top_k", self.top_k)
        return resolved

    def update(self, tool_name: str, result: Any) -> None:
        if not isinstance(result, list):
            return
        if tool_name in SOURCE_TOOLS:
            self.collected_items.extend(result)
            self.current_items = self.collected_items
        elif tool_name == "extract_article_text":
            self.current_items = result
        elif tool_name == "deduplicate_and_rank":
            self.ranked_items = result
            self.current_items = result


def parse_tool_arguments(raw_arguments: str | None) -> dict[str, Any]:
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


STRUCTURED_OUTPUT_RE = re.compile(
    r"^("
    r"\d+[\.\、)]\s+|"
    r"(标题|来源|时间|摘要|重要性|为什么重要|链接|原始链接)[:：]"
    r")"
)
LABEL_ONLY_RE = re.compile(r"^(标题|来源|时间|摘要|重要性|为什么重要|链接|原始链接)[:：]\s*$")
URL_CONTINUATION_RE = re.compile(r"https?://\S*$")


def continuation_separator(previous: str) -> str:
    if LABEL_ONLY_RE.match(previous):
        return ""
    if URL_CONTINUATION_RE.search(previous) or previous.endswith(("/", "?", "&", "=", "-", "_")):
        return ""
    return " "


def normalize_assistant_linebreaks(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in {"---", "***", "___"}:
            continue
        stripped = stripped.lstrip("#").strip() if stripped.startswith("#") else stripped
        stripped = stripped.replace("**", "").replace("__", "").strip()

        if not stripped:
            if normalized and normalized[-1]:
                normalized.append("")
            continue

        if not normalized or not normalized[-1]:
            normalized.append(stripped)
            continue

        if STRUCTURED_OUTPUT_RE.match(stripped):
            normalized.append(stripped)
            continue

        separator = continuation_separator(normalized[-1])
        normalized[-1] = f"{normalized[-1]}{separator}{stripped}".strip()

    while normalized and not normalized[0]:
        normalized.pop(0)
    while normalized and not normalized[-1]:
        normalized.pop()
    return normalized


def sanitize_assistant_output(content: str) -> str:
    return "\n".join(normalize_assistant_linebreaks(content.splitlines()))


def tool_result_message(tool_call_id: str, result: Any) -> dict[str, str]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def mock_intake_response(user_input: str) -> NewsRequest | str:
    import re

    text = user_input.strip()
    if not text:
        return "请先告诉我你想看哪类 AI 新闻。"

    hours: int | None = None
    if any(keyword in text for keyword in ["今天", "今日", "24小时", "一天", "过去一天"]):
        hours = 24
    elif "昨天" in text:
        hours = 48
    elif "一周" in text or "7天" in text or "七天" in text:
        hours = 168
    else:
        day_match = re.search(r"最近\s*([一二两三四五六七八九十0-9]+)\s*天", text)
        hour_match = re.search(r"过去\s*(\d+)\s*小时", text)
        if hour_match:
            hours = int(hour_match.group(1))
        elif day_match:
            raw_days = day_match.group(1)
            zh_digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            days = int(raw_days) if raw_days.isdigit() else zh_digits.get(raw_days)
            if days:
                hours = days * 24

    top_k: int | None = None
    count_match = re.search(r"(\d+)\s*条", text)
    if count_match:
        top_k = int(count_match.group(1))
    else:
        zh_count_match = re.search(r"([一二两三四五六七八九十])\s*条", text)
        if zh_count_match:
            top_k = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}[zh_count_match.group(1)]

    missing: list[str] = []
    if hours is None:
        missing.append("时间范围")
    if top_k is None:
        missing.append("新闻数量")
    if missing:
        return "还需要补充：" + "、".join(missing) + "。例如：过去24小时，5条。"

    question = next((line.strip() for line in text.splitlines() if line.strip()), text)
    return NewsRequest(question=question, hours=max(1, min(hours, 24 * 30)), top_k=max(1, min(top_k, 20)))


async def run_intake_turn(
    *,
    user_input: str,
    messages: list[dict[str, Any]],
    cache: ConversationCache,
    mock_llm: bool = False,
) -> NewsRequest | str:
    cache.append("intake_user", {"content": user_input})
    if mock_llm:
        messages.append({"role": "user", "content": user_input})
        combined_input = "\n".join(message["content"] for message in messages if message.get("role") == "user")
        result = mock_intake_response(combined_input)
        if isinstance(result, NewsRequest):
            cache.append("intake_request", result.model_dump())
            messages.clear()
            messages.append({"role": "system", "content": INTAKE_SYSTEM_PROMPT})
        else:
            cache.append("intake_assistant", {"content": result, "mock_llm": True})
        return result

    messages.append({"role": "user", "content": user_input})
    client = DeepSeekClient()
    message = await asyncio.to_thread(client.complete, messages, tools=INTAKE_TOOL_SCHEMAS)
    tool_calls = getattr(message, "tool_calls", None) or []
    for tool_call in tool_calls:
        request = news_request_from_tool_call(tool_call)
        if request:
            cache.append("intake_request", request.model_dump())
            messages.clear()
            messages.append({"role": "system", "content": INTAKE_SYSTEM_PROMPT})
            return request

    content = sanitize_assistant_output(message.content or "")
    messages.append({"role": "assistant", "content": content})
    cache.append("intake_assistant", {"content": content})
    return content


async def execute_tool_with_cache(
    *,
    caller: ToolCaller,
    cache: ConversationCache,
    state: NewsToolState,
    tool_name: str,
    model_arguments: dict[str, Any],
    tool_call_id: str | None = None,
    optional: bool = False,
) -> Any:
    if tool_name not in NEWS_TOOLS:
        error = f"Unsupported tool: {tool_name}"
        cache.append("error", {"message": error, "tool": tool_name})
        raise RuntimeError(error)

    resolved = state.resolve_arguments(tool_name, model_arguments)
    cache.append(
        "tool_call",
        {
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "model_arguments": model_arguments,
            "resolved_arguments": compact_arguments(resolved),
        },
    )
    try:
        result = await caller.call(tool_name, resolved, optional=optional)
    except Exception as exc:
        cache.append("error", {"tool": tool_name, "tool_call_id": tool_call_id, "message": str(exc)})
        raise

    state.update(tool_name, result)
    cache.append(
        "tool_result",
        {
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "result_count": result_count(result),
            "result": result,
        },
    )
    return result


async def run_mock_chat(
    *,
    question: str,
    hours: int,
    top_k: int,
    session_id: str,
    cache_user: bool = True,
) -> dict[str, Any]:
    configure_logging()
    cache = ConversationCache(session_id)
    if cache_user:
        cache.append("user", {"content": question, "hours": hours, "top_k": top_k, "mock_llm": True})
    state = NewsToolState(hours=hours, top_k=top_k)
    server = StdioServerParameters(command=sys.executable, args=["-m", "ai_news.mcp_server"])

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            caller = ToolCaller(session)
            for tool_name in ["fetch_rss_items", "search_arxiv_papers", "search_hackernews_stories"]:
                await execute_tool_with_cache(
                    caller=caller,
                    cache=cache,
                    state=state,
                    tool_name=tool_name,
                    model_arguments={},
                    optional=True,
                )
            await execute_tool_with_cache(
                caller=caller,
                cache=cache,
                state=state,
                tool_name="extract_article_text",
                model_arguments={},
            )
            ranked = await execute_tool_with_cache(
                caller=caller,
                cache=cache,
                state=state,
                tool_name="deduplicate_and_rank",
                model_arguments={"top_k": top_k},
            )

    content = generate_mock_chat(ranked, hours, question)
    cache.append("assistant", {"content": content, "mock_llm": True})
    return {"content": content, "ranked_items": ranked, "cache_path": str(cache.path)}


async def run_chat(
    *,
    question: str,
    hours: int = 24,
    top_k: int = 5,
    session_id: str = "default",
    mock_llm: bool = False,
    max_tool_rounds: int = 4,
    cache_user: bool = True,
) -> dict[str, Any]:
    if mock_llm:
        return await run_mock_chat(
            question=question,
            hours=hours,
            top_k=top_k,
            session_id=session_id,
            cache_user=cache_user,
        )

    configure_logging()
    cache = ConversationCache(session_id)
    if cache_user:
        cache.append("user", {"content": question, "hours": hours, "top_k": top_k, "mock_llm": False})
    state = NewsToolState(hours=hours, top_k=top_k)
    client = DeepSeekClient()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{question}\n\n"
                f"查询范围：过去 {hours} 小时。最多输出 {top_k} 条。"
                "请按 system prompt 的 MCP tool 流程先调用工具。"
            ),
        },
    ]
    server = StdioServerParameters(command=sys.executable, args=["-m", "ai_news.mcp_server"])

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            caller = ToolCaller(session)

            for _round in range(max_tool_rounds):
                message = await asyncio.to_thread(client.complete, messages, tools=NEWS_TOOL_SCHEMAS)
                tool_calls = getattr(message, "tool_calls", None) or []
                if not tool_calls:
                    content = sanitize_assistant_output(message.content or "")
                    cache.append("assistant", {"content": content})
                    return {
                        "content": content,
                        "ranked_items": state.ranked_items,
                        "cache_path": str(cache.path),
                        "trace": caller.trace,
                    }

                messages.append(assistant_message_to_dict(message))
                for tool_call in tool_calls:
                    tool_payload = tool_call_to_dict(tool_call)
                    tool_name = tool_payload["function"]["name"]
                    model_arguments = parse_tool_arguments(tool_payload["function"]["arguments"])
                    result = await execute_tool_with_cache(
                        caller=caller,
                        cache=cache,
                        state=state,
                        tool_name=tool_name,
                        model_arguments=model_arguments,
                        tool_call_id=tool_payload["id"],
                    )
                    messages.append(tool_result_message(tool_payload["id"], result))

            messages.append(
                {
                    "role": "user",
                    "content": "工具调用轮次已达到上限。请基于已有 tool results 直接输出最终中文编号新闻消息。",
                }
            )
            final_message = await asyncio.to_thread(client.complete, messages, tools=None)
            content = sanitize_assistant_output(final_message.content or "")
            cache.append("assistant", {"content": content, "max_tool_rounds_reached": True})
            return {
                "content": content,
                "ranked_items": state.ranked_items,
                "cache_path": str(cache.path),
                "trace": caller.trace,
            }


async def run_interactive_session(
    *,
    session_id: str,
    input_func: Any,
    output_func: Any,
    mock_llm: bool = False,
) -> None:
    configure_logging()
    cache = ConversationCache(session_id)
    output_func("AI 新闻助手已启动。你可以直接描述想看的 AI 新闻；输入 exit、quit 或 q 退出。")
    output_func(f"会话缓存：{cache.path}")
    intake_messages: list[dict[str, Any]] = [{"role": "system", "content": INTAKE_SYSTEM_PROMPT}]

    while True:
        user_input = await asyncio.to_thread(input_func, "你> ")
        normalized = user_input.strip()
        if normalized.lower() in {"exit", "quit", "q"}:
            cache.append("session_end", {"reason": "user_exit"})
            output_func("已退出。")
            return
        if not normalized:
            continue

        intake_result = await run_intake_turn(
            user_input=normalized,
            messages=intake_messages,
            cache=cache,
            mock_llm=mock_llm,
        )
        if isinstance(intake_result, str):
            output_func(f"助手> {intake_result}")
            continue

        request = intake_result
        output_func(f"助手> 已了解，我会查询过去 {request.hours} 小时内与“{request.question}”相关的 {request.top_k} 条新闻。")
        output_func("助手> 正在调用 MCP tools 检索新闻...")
        result = await run_chat(
            question=request.question,
            hours=request.hours,
            top_k=request.top_k,
            session_id=cache.session_id,
            mock_llm=mock_llm,
            cache_user=False,
        )
        output_func(f"助手>\n{result['content']}")
        intake_messages = [{"role": "system", "content": INTAKE_SYSTEM_PROMPT}]
