from __future__ import annotations

from typer.testing import CliRunner

from ai_news.cli import app


def test_start_command_accepts_no_news_parameters_and_exits():
    runner = CliRunner()

    result = runner.invoke(app, ["start", "--session", "cli-smoke", "--mock-llm"], input="q\n")

    assert result.exit_code == 0
    assert "AI 新闻助手已启动" in result.output
    assert "已退出" in result.output
