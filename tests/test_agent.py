from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ai_news.agent import decode_mcp_result, mock_intake_response, run_intake_turn, sanitize_assistant_output
from ai_news.conversation_cache import ConversationCache
from ai_news.deepseek_client import INTAKE_SYSTEM_PROMPT
from ai_news.models import NewsRequest


def test_decode_mcp_result_unwraps_fastmcp_result():
    result = SimpleNamespace(structuredContent={"result": [{"title": "AI news"}]}, content=[])

    decoded = decode_mcp_result(result)

    assert decoded == [{"title": "AI news"}]


def test_sanitize_assistant_output_removes_markdown_decoration():
    content = "## 标题\n\n---\n\n1. **News**\n   来源：__Example__"

    sanitized = sanitize_assistant_output(content)

    assert "---" not in sanitized
    assert "##" not in sanitized
    assert "**" not in sanitized
    assert "__" not in sanitized


def test_mock_intake_asks_for_missing_required_fields():
    response = mock_intake_response("我想看AI新闻")

    assert isinstance(response, str)
    assert "时间范围" in response
    assert "新闻数量" in response


def test_mock_intake_returns_structured_request_when_complete():
    response = mock_intake_response("我想看今天AI模型发布相关的5条新闻")

    assert isinstance(response, NewsRequest)
    assert response.hours == 24
    assert response.top_k == 5


def test_mock_intake_turn_remembers_previous_user_input(tmp_path):
    async def scenario():
        cache = ConversationCache("intake-test", root=tmp_path)
        messages = [{"role": "system", "content": INTAKE_SYSTEM_PROMPT}]
        first = await run_intake_turn(
            user_input="我想看AI模型发布新闻",
            messages=messages,
            cache=cache,
            mock_llm=True,
        )
        second = await run_intake_turn(
            user_input="今天5条",
            messages=messages,
            cache=cache,
            mock_llm=True,
        )
        return first, second, cache.read()

    first, second, events = asyncio.run(scenario())

    assert isinstance(first, str)
    assert isinstance(second, NewsRequest)
    assert second.question.startswith("我想看AI模型发布新闻")
    assert {event.type for event in events} >= {"intake_user", "intake_assistant", "intake_request"}
