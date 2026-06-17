from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

DEFAULT_RSS_SOURCES = [
    "https://openai.com/news/rss.xml",
    "https://github.com/openai/openai-python/releases.atom",
    "https://github.com/modelcontextprotocol/python-sdk/releases.atom",
]

DEFAULT_ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]
DEFAULT_HN_TERMS = ["AI", "LLM", "OpenAI", "DeepSeek", "MCP", "AI agent"]

AI_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "llm",
    "large language model",
    "machine learning",
    "deep learning",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "deepseek",
    "mcp",
    "model context protocol",
    "inference",
    "reasoning",
    "multimodal",
]

ROOT_DIR = Path.cwd()
OUTPUTS_DIR = ROOT_DIR / "outputs"
DIGESTS_DIR = OUTPUTS_DIR / "digests"
TRACES_DIR = OUTPUTS_DIR / "traces"
LOGS_DIR = ROOT_DIR / "logs"
LOG_FILE = LOGS_DIR / "agent.log"
