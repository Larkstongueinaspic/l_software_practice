from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from openai import OpenAI

from ai_news.config import DEEPSEEK_BASE_URL, DEFAULT_MODEL
from ai_news.models import NewsRequest, RankedNewsItem


SYSTEM_PROMPT = """你是一个中文 AI 新闻对话 Agent。你通过本地 MCP server 暴露的 tools 获取真实上下文，再回答用户。

MCP server 工具格式要求：
1. fetch_rss_items(sources?: string[], hours?: integer, limit_per_source?: integer)
   - 从 RSS/Atom 源获取 AI 公司动态和 GitHub release。
   - 返回 NewsItem[]，字段包括 id, title, url, source, published_at, summary, raw_text, tags。
2. search_arxiv_papers(categories?: string[], hours?: integer, max_results?: integer)
   - 查询 arXiv AI/ML/NLP 论文。
   - 返回 NewsItem[]。
3. search_hackernews_stories(terms?: string[], hours?: integer, max_results?: integer)
   - 查询 Hacker News 上的 AI/LLM/MCP 讨论。
   - 返回 NewsItem[]。
4. extract_article_text(items?: NewsItem[], max_chars?: integer, timeout_seconds?: integer)
   - 抽取网页正文。如果你省略 items 或传空数组，Agent 会自动使用前面已收集的新闻。
   - 返回增强后的 NewsItem[]。
5. deduplicate_and_rank(items?: NewsItem[], top_k?: integer)
   - 去重并排序。如果你省略 items 或传空数组，Agent 会自动使用最新已抽取的新闻。
   - 返回 RankedNewsItem[]，额外包含 score 和 reason。

行为规则：
- 回答广义 AI 新闻问题时，先调用至少两个外部来源工具，再调用 extract_article_text 和 deduplicate_and_rank。
- 不得凭模型记忆编造新闻、链接、日期、数据或引用。
- 最终答案直接作为对话消息输出，不生成 Markdown 日报，不使用 Markdown 标题、分隔线、加粗、引用块或代码块。
- 最终答案用中文轻量编号列表，只使用普通纯文本。每条包含：标题、来源、时间、摘要、为什么重要、原始链接。
- 如果工具结果不足，明确说明信息不足，而不是补编内容。
"""

INTAKE_SYSTEM_PROMPT = """你是 AI 新闻助手的命令行引导员。你的任务是在调用新闻 MCP tools 前，先通过自然中文对话收集完整查询需求。

必须收集三项信息：
1. 新闻问题或主题，例如“今天 AI 新闻有哪些”“最近模型发布”“AI Agent 相关新闻”。
2. 时间范围，并转换成 hours 整数。例如“今天/过去一天”=24，“最近三天”=72，“一周”=168。
3. 新闻数量 top_k，必须是 1 到 20 的整数。

如果用户缺少任何一项，你只能用简短中文追问缺失项，不要调用 submit_news_request。
当三项信息都明确后，必须调用 submit_news_request，不要直接回答新闻内容。
不要凭空补默认值；如果用户含糊，就追问。
"""

INTAKE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "submit_news_request",
            "description": "Submit the completed news query requirements after collecting them from the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's concrete news question or topic.",
                    },
                    "hours": {
                        "type": "integer",
                        "description": "Lookback window in hours, such as 24 for today or 72 for the last three days.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of news items requested, from 1 to 20.",
                    },
                },
                "required": ["question", "hours", "top_k"],
                "additionalProperties": False,
            },
        },
    }
]


NEWS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_rss_items",
            "description": "Fetch AI news from RSS and Atom feeds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional feed URLs. Omit to use defaults.",
                    },
                    "hours": {"type": "integer", "description": "Lookback window in hours."},
                    "limit_per_source": {"type": "integer", "description": "Maximum items per feed."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_arxiv_papers",
            "description": "Search recent AI, ML, and NLP papers from arXiv.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional arXiv categories such as cs.AI, cs.LG, cs.CL.",
                    },
                    "hours": {"type": "integer", "description": "Lookback window in hours."},
                    "max_results": {"type": "integer", "description": "Maximum number of papers."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hackernews_stories",
            "description": "Search recent Hacker News AI and LLM stories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Search terms. Omit to use default AI terms.",
                    },
                    "hours": {"type": "integer", "description": "Lookback window in hours."},
                    "max_results": {"type": "integer", "description": "Maximum number of stories."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_article_text",
            "description": "Extract article text for collected news items. Omit items to use accumulated news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional NewsItem array. Omit or pass [] to use accumulated news.",
                    },
                    "max_chars": {"type": "integer", "description": "Maximum characters per article."},
                    "timeout_seconds": {"type": "integer", "description": "HTTP timeout per article."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deduplicate_and_rank",
            "description": "Deduplicate and rank collected news. Omit items to use latest extracted news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional NewsItem array. Omit or pass [] to use latest extracted news.",
                    },
                    "top_k": {"type": "integer", "description": "Number of top items to return."},
                },
                "additionalProperties": False,
            },
        },
    },
]


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = DEEPSEEK_BASE_URL,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model or os.getenv("AI_NEWS_MODEL") or DEFAULT_MODEL
        self.base_url = base_url

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set. Use --mock-llm for a local demo.")

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message


def assistant_message_to_dict(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        payload["tool_calls"] = [tool_call_to_dict(tool_call) for tool_call in tool_calls]
    return payload


def tool_call_to_dict(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments or "{}",
        },
    }


def news_request_from_tool_call(tool_call: Any) -> NewsRequest | None:
    payload = tool_call_to_dict(tool_call)
    if payload["function"]["name"] != "submit_news_request":
        return None
    try:
        arguments = payload["function"]["arguments"]
        import json

        raw = json.loads(arguments) if arguments else {}
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        raw["hours"] = max(1, min(int(raw["hours"]), 24 * 30))
        raw["top_k"] = max(1, min(int(raw["top_k"]), 20))
        return NewsRequest.model_validate(raw)
    except (KeyError, TypeError, ValueError):
        return None


def generate_mock_chat(items: list[dict[str, Any]], hours: int, question: str) -> str:
    ranked_items = [RankedNewsItem.model_validate(item) for item in items]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"根据过去 {hours} 小时内 MCP tools 获取到的新闻，我找到 {len(ranked_items)} 条较值得关注的信息。生成时间：{generated_at}。",
        f"你的问题：{question}",
        "",
    ]
    for index, item in enumerate(ranked_items, start=1):
        summary = item.summary or item.raw_text or item.title
        lines.extend(
            [
                f"{index}. {item.title}",
                f"   来源：{item.source}",
                f"   时间：{item.published_at}",
                f"   摘要：{summary[:220]}",
                f"   重要性：{item.reason}",
                f"   链接：{item.url}",
                "",
            ]
        )
    return "\n".join(lines).strip()
