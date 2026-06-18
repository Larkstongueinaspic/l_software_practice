from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai_news.config import CONVERSATIONS_DIR
from ai_news.models import ConversationEvent
from ai_news.tools import isoformat, utc_now


def normalize_session_id(session_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id.strip())
    return normalized.strip(".-") or "default"


class ConversationCache:
    def __init__(self, session_id: str = "default", root: Path | None = None) -> None:
        self.session_id = normalize_session_id(session_id)
        self.root = root or CONVERSATIONS_DIR
        self.path = self.root / f"{self.session_id}.jsonl"

    def append(self, event_type: str, data: dict[str, Any]) -> ConversationEvent:
        self.root.mkdir(parents=True, exist_ok=True)
        event = ConversationEvent(
            session_id=self.session_id,
            type=event_type,
            timestamp=isoformat(utc_now()),
            data=data,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    def read(self, limit: int | None = None) -> list[ConversationEvent]:
        if not self.path.exists():
            return []
        events: list[ConversationEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(ConversationEvent.model_validate(json.loads(line)))
        return events[-limit:] if limit else events
