from __future__ import annotations

import re

from typer.testing import CliRunner

from ai_news import cli
from ai_news.cli import app

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def test_start_command_accepts_no_news_parameters_and_exits():
    runner = CliRunner()

    result = runner.invoke(app, ["start", "--session", "cli-smoke", "--mock-llm"], input="q\n")

    assert result.exit_code == 0
    assert "AI 新闻助手已启动" in result.output
    assert "已退出" in result.output


def test_print_message_keeps_rich_highlight_without_hard_wrapping(monkeypatch, capsys):
    monkeypatch.setattr(cli, "console", cli.Console(width=80, force_terminal=True))
    text = (
        "2. Stack Overflow for Agents 公测发布 —— 来源 Stack Overflow Blog，2026-06-10。"
        "Stack Overflow 正式推出面向 AI Agent 的 API 优先知识交换平台，采用多 Agent 验证循环确保知识可信度。"
        "https://stackoverflow.blog/2026/06/10/announcing-stack-overflow-for-agents/"
    )

    cli.print_message(text)

    output = strip_ansi(capsys.readouterr().out)
    assert "Stack Overflow \nBlog" not in output
    assert "announci\nng" not in output
    assert text in output


def test_print_message_colors_assistant_label(monkeypatch, capsys):
    monkeypatch.setattr(cli, "console", cli.Console(width=80, force_terminal=True, color_system="standard"))

    cli.print_message("助手> 正在调用 MCP tools")

    output = capsys.readouterr().out
    assert "\x1b[" in output
    assert "助手>" in strip_ansi(output)
