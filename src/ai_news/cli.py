from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from ai_news.agent import run_digest
from ai_news.config import (
    DEFAULT_ARXIV_CATEGORIES,
    DEFAULT_HN_TERMS,
    DEFAULT_RSS_SOURCES,
    OUTPUTS_DIR,
)

app = typer.Typer(help="Daily AI News Intelligence Agent")
console = Console()


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

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    checks.append(("outputs directory", OUTPUTS_DIR.exists(), str(OUTPUTS_DIR)))

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
def digest(
    hours: int = typer.Option(24, min=1, help="Lookback window in hours."),
    top_k: int = typer.Option(8, min=1, max=20, help="Number of ranked items in the digest."),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Generate a deterministic local digest without DeepSeek."),
    output_dir: Path = typer.Option(Path("outputs"), help="Root directory for digests and traces."),
) -> None:
    """Generate a Chinese AI news digest."""
    result = asyncio.run(run_digest(hours=hours, top_k=top_k, mock_llm=mock_llm, output_dir=output_dir))
    write_result = result["write_result"]
    console.print("[bold green]Digest generated[/bold green]")
    console.print(f"Markdown: {write_result['digest_path']}")
    console.print(f"Trace: {write_result['trace_path']}")
    console.print(f"Items: {write_result['item_count']}")


@app.command("install-cron")
def install_cron(
    time: str = typer.Option("08:00", help="Daily run time in HH:MM format."),
    top_k: int = typer.Option(8, min=1, max=20),
    apply: bool = typer.Option(False, "--apply", help="Install into the current user's crontab."),
) -> None:
    """Print or install a cron entry for daily digest generation."""
    try:
        hour_text, minute_text = time.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError as exc:
        raise typer.BadParameter("time must be HH:MM, for example 08:00") from exc

    cwd = Path.cwd()
    command = (
        f"cd {cwd} && {sys.executable} -m ai_news.cli digest "
        f"--hours 24 --top-k {top_k} >> logs/cron.log 2>&1"
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
