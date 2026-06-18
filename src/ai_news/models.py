from __future__ import annotations

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    id: str
    title: str
    url: str
    source: str
    published_at: str
    summary: str = ""
    raw_text: str = ""
    tags: list[str] = Field(default_factory=list)


class RankedNewsItem(NewsItem):
    score: float = 0.0
    reason: str = ""


class Digest(BaseModel):
    date: str
    generated_at: str
    items: list[RankedNewsItem]
    overall_summary: str = ""
    output_path: str = ""


class ToolTrace(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)
    timestamp: str
    duration_ms: float
    result_count: int | None = None
    error: str | None = None


class ConversationEvent(BaseModel):
    session_id: str
    type: str
    timestamp: str
    data: dict = Field(default_factory=dict)


class NewsRequest(BaseModel):
    question: str
    hours: int = Field(ge=1, le=24 * 30)
    top_k: int = Field(ge=1, le=20)
