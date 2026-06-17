from __future__ import annotations

from types import SimpleNamespace

from ai_news.agent import decode_mcp_result


def test_decode_mcp_result_unwraps_fastmcp_result():
    result = SimpleNamespace(structuredContent={"result": [{"title": "AI news"}]}, content=[])

    decoded = decode_mcp_result(result)

    assert decoded == [{"title": "AI news"}]
