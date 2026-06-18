from __future__ import annotations

from ai_news.conversation_cache import ConversationCache, normalize_session_id


def test_conversation_cache_appends_and_reads_jsonl(tmp_path):
    cache = ConversationCache("test/session", root=tmp_path)

    cache.append("user", {"content": "今天AI新闻有哪些？"})
    cache.append("assistant", {"content": "1. 新闻"})
    events = cache.read()

    assert cache.session_id == "test-session"
    assert len(events) == 2
    assert events[0].type == "user"
    assert events[1].data["content"] == "1. 新闻"
    assert cache.path.exists()


def test_normalize_session_id_defaults_when_blank():
    assert normalize_session_id("  ") == "default"
