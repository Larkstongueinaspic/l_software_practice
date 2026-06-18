from __future__ import annotations

import asyncio
import importlib.util
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from ai_news.agent import run_chat, run_interactive_session
from ai_news.config import (
    CONVERSATIONS_DIR,
    DEFAULT_ARXIV_CATEGORIES,
    DEFAULT_HN_TERMS,
    DEFAULT_RSS_SOURCES,
)
from ai_news.conversation_cache import ConversationCache

app = typer.Typer(help="Daily AI News Intelligence Agent")
console = Console()


def default_interactive_session_id() -> str:
    return "interactive-" + datetime.now().strftime("%Y%m%d-%H%M%S")


@app.command()
def start(
    session: str | None = typer.Option(None, "--session", help="Conversation cache session id."),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Run a deterministic local intake and answer flow."),
) -> None:
    """Start the interactive AI news assistant."""
    session_id = session or default_interactive_session_id()
    asyncio.run(
        run_interactive_session(
            session_id=session_id,
            input_func=console.input,
            output_func=console.print,
            mock_llm=mock_llm,
        )
    )


@app.command()
def sources() -> None:
    """List default news and context sources."""
    table = Table(title="Default AI News Sources")
    table.add_column("Type")
    table.add_column("Value")
    for source in DEFAULT_RSS_SOURCES:
        table.add_row("RSS/Atom", source)
    table.add_row("arXiv categories", ", ".join(DEFAULT_ARXIV_CATEGORIES))
    table.add_row("Hacker News terms", ", ".join(DEFAULT_HN_TERMS))
    console.print(table)


@app.command()
def doctor() -> None:
    """Check local environment, dependencies, API key, and basic network access."""
    checks: list[tuple[str, bool, str]] = []
    checks.append(("DEEPSEEK_API_KEY", bool(os.getenv("DEEPSEEK_API_KEY")), "required unless --mock-llm is used"))
    checks.append(("mcp package", importlib.util.find_spec("mcp") is not None, "required for local MCP tools"))
    checks.append(("openai package", importlib.util.find_spec("openai") is not None, "required for DeepSeek API"))

    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    checks.append(("conversation cache", CONVERSATIONS_DIR.exists(), str(CONVERSATIONS_DIR)))

    network_targets = [
        ("OpenAI RSS", "https://openai.com/news/rss.xml"),
        ("HN Algolia", "https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&hitsPerPage=1"),
        ("arXiv API", "https://export.arxiv.org/api/query?search_query=cat:cs.AI&start=0&max_results=1"),
    ]
    for name, url in network_targets:
        ok = False
        detail = url
        try:
            response = httpx.get(url, timeout=12, follow_redirects=True)
            ok = response.status_code < 500
            detail = f"{url} -> HTTP {response.status_code}"
        except Exception as exc:
            detail = f"{url} -> {exc}"
        checks.append((name, ok, detail))

    table = Table(title="ai-news doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail in checks:
        table.add_row(name, "OK" if ok else "WARN", detail)
    console.print(table)


@app.command()
def chat(
    question: str = typer.Argument(..., help="News question to ask the agent."),
    hours: int = typer.Option(24, min=1, help="Lookback window in hours."),
    top_k: int = typer.Option(5, min=1, max=20, help="Number of ranked items in the answer."),
    session: str = typer.Option("default", "--session", help="Conversation cache session id."),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Run MCP tools and generate a deterministic local answer."),
) -> None:
    """Ask a legacy single-turn question. Prefer `ai-news start` for the guided app flow."""
    result = asyncio.run(
        run_chat(question=question, hours=hours, top_k=top_k, session_id=session, mock_llm=mock_llm)
    )
    console.print(result["content"])


@app.command()
def history(
    session: str = typer.Option("default", "--session", help="Conversation cache session id."),
    limit: int = typer.Option(20, min=1, help="Number of latest events to show."),
) -> None:
    """Show cached conversation events."""
    cache = ConversationCache(session)
    events = cache.read(limit=limit)
    table = Table(title=f"Conversation history: {cache.session_id}")
    table.add_column("Time")
    table.add_column("Type")
    table.add_column("Preview")
    for event in events:
        preview = event.data.get("content") or event.data.get("tool") or event.data.get("message") or str(event.data)
        preview = str(preview).replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:97] + "..."
        table.add_row(event.timestamp, event.type, preview)
    console.print(table)
    console.print(f"Cache: {cache.path}")


@app.command("install-cron")
def install_cron(
    time: str = typer.Option("08:00", help="Daily run time in HH:MM format."),
    question: str = typer.Option("今天AI新闻有哪些？", help="Question to ask each day."),
    top_k: int = typer.Option(5, min=1, max=20),
    session: str = typer.Option("daily", help="Conversation cache session id."),
    apply: bool = typer.Option(False, "--apply", help="Install into the current user's crontab."),
) -> None:
    """Print or install a cron entry for daily chat generation."""
    try:
        hour_text, minute_text = time.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError as exc:
        raise typer.BadParameter("time must be HH:MM, for example 08:00") from exc

    cwd = Path.cwd()
    quoted_question = shlex.quote(question)
    command = (
        f"cd {cwd} && {sys.executable} -m ai_news.cli chat {quoted_question} "
        f"--hours 24 --top-k {top_k} --session {shlex.quote(session)} >> logs/cron.log 2>&1"
    )
    cron_line = f"{minute} {hour} * * * {command}"
    console.print(cron_line)

    if apply:
        existing = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
        current = existing.stdout if existing.returncode == 0 else ""
        if cron_line not in current:
            updated = current.rstrip() + "\n" + cron_line + "\n"
            subprocess.run(["crontab", "-"], input=updated, text=True, check=True)
        console.print("[bold green]Cron entry installed.[/bold green]")
    else:
        console.print("Use --apply to install it. Make sure DEEPSEEK_API_KEY is available to cron.")


if __name__ == "__main__":
    app()
