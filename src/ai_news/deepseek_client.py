from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from openai import OpenAI

from ai_news.config import DEEPSEEK_BASE_URL, DEFAULT_MODEL
from ai_news.models import RankedNewsItem


SYSTEM_PROMPT = """You are a Chinese AI news intelligence editor.
You must summarize only the news items provided by tools.
Do not invent facts, links, dates, organizations, metrics, or quotes.
Keep original English titles and source links.
Write concise Chinese suitable for a daily technical news digest."""


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

    def generate_digest(
        self,
        items: list[dict[str, Any]],
        hours: int,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set. Use --mock-llm for a local demo.")

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        payload = {
            "hours": hours,
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [self._compact_item(item) for item in items],
        }
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请根据以下工具返回的结构化新闻生成 Markdown 中文 AI 新闻日报。"
                        "格式包含标题、总览、重点新闻列表和来源链接。\n\n"
                        + json.dumps(payload, ensure_ascii=False)
                    ),
                },
            ],
            temperature=0.2,
            stream=False,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek returned an empty digest.")
        return content

    @staticmethod
    def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
        ranked = RankedNewsItem.model_validate(item)
        return {
            "title": ranked.title,
            "url": ranked.url,
            "source": ranked.source,
            "published_at": ranked.published_at,
            "summary": ranked.summary[:800],
            "raw_text": ranked.raw_text[:1600],
            "tags": ranked.tags,
            "score": ranked.score,
            "rank_reason": ranked.reason,
        }


def generate_mock_digest(items: list[dict[str, Any]], hours: int) -> str:
    ranked_items = [RankedNewsItem.model_validate(item) for item in items]
    date_str = datetime.now(UTC).date().isoformat()
    lines = [
        f"# AI 新闻日报 - {date_str}",
        "",
        f"过去 {hours} 小时内，Agent 通过 MCP tools 收集并筛选了 {len(ranked_items)} 条 AI 相关信息。",
        "以下内容由本地 mock LLM 模式生成，用于无 API key 的演示和截图。",
        "",
        "## 总览",
        "",
        "今日重点集中在模型发布、开发者工具、论文进展和社区讨论。所有条目均来自工具返回的外部来源。",
        "",
        "## 重点新闻",
        "",
    ]
    for index, item in enumerate(ranked_items, start=1):
        summary = item.summary or item.raw_text or item.title
        lines.extend(
            [
                f"### {index}. {item.title}",
                "",
                f"- 来源：{item.source}",
                f"- 发布时间：{item.published_at}",
                f"- 链接：{item.url}",
                f"- 一句话摘要：{summary[:220]}",
                f"- 为什么重要：排序原因 `{item.reason}`，说明该条目在来源可信度、时效性或 AI 关键词上更突出。",
                "",
            ]
        )
    return "\n".join(lines)
