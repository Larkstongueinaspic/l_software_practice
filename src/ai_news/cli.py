from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime

import httpx
import typer
from rich.console import Console
from rich.markup import escape
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


USER_LABEL = "你>"
ASSISTANT_LABEL = "助手>"


def prompt_user(prompt: str = "") -> str:
    if prompt.strip() == USER_LABEL:
        return console.input(f"[bold cyan]{USER_LABEL}[/bold cyan] ")
    return console.input(prompt)


def render_labelled_message(message: str, label: str, style: str) -> str:
    rest = message[len(label) :]
    separator = ""
    if rest.startswith(" "):
        separator = " "
        rest = rest[1:]
    elif rest.startswith("\n"):
        separator = "\n"
        rest = rest[1:]
    return f"[{style}]{label}[/{style}]{separator}{escape(rest)}"


def print_message(message: str) -> None:
    if message.startswith(ASSISTANT_LABEL):
        rendered = render_labelled_message(message, ASSISTANT_LABEL, "bold green")
        console.print(rendered, markup=True, highlight=True, soft_wrap=True)
        return
    if message.startswith(USER_LABEL):
        rendered = render_labelled_message(message, USER_LABEL, "bold cyan")
        console.print(rendered, markup=True, highlight=True, soft_wrap=True)
        return
    console.print(escape(message), markup=True, highlight=True, soft_wrap=True)


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
            input_func=prompt_user,
            output_func=print_message,
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
    print_message(result["content"])


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


if __name__ == "__main__":
    app()
