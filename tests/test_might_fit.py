"""Attention: a few memories the message does not touch, ranked in code, rotated across replies."""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from agent.context_engine.assembly.sources import _might_fit_sources
from agent.memory_engine.memories.retrieval import might_fit_memories
from storage import create_agent_memory, reset_db, save_conversation

USER_ID = "might-fit-user"
CHAT = "might-fit-chat"
NOW = datetime(2026, 10, 6, 21, 0, tzinfo=UTC)


def _memory(key: str, statement: str, *, kind: str = "semantic", importance: float = 0.5, occurred_at: str | None = None) -> str:
    source = f"src-{key}"
    save_conversation({"id": source, "status": "completed", "messages": [{"role": "user", "content": statement}]}, USER_ID)
    return create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": kind,
            "purposes": ["personalization"],
            "key": key,
            "value": statement,
            "statement": statement,
            "confidence": 0.9,
            "importance": importance,
            "occurred_at": occurred_at,
            "evidence": [{"conversation_id": source, "message_index": 0, "exact_quote": statement, "observed_at": "2026-10-01T10:00:00+00:00"}],
        }
    )["id"]


class MightFitTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CHAT, "status": "active", "messages": []}, USER_ID)
        self.films = _memory("films", "Loves old black-and-white films.", importance=0.8)
        self.exam = _memory("exam", "Has a driving test on Thu 8 Oct.", kind="episodic", importance=0.4, occurred_at=(NOW + timedelta(days=2)).isoformat())
        self.past = _memory("trip", "Went to Goa in March.", kind="episodic", importance=0.9, occurred_at="2026-03-15T12:00:00+00:00")
        self.style = _memory("style", "Wants short replies.", kind="procedural", importance=1.0)

    def _ids(self, **kwargs) -> list[str]:
        return [memory["id"] for memory in might_fit_memories(USER_ID, now=NOW, **{"exclude_ids": set(), "recently_offered": set(), **kwargs})]

    def test_coming_up_soon_comes_first_and_how_to_talk_stays_out(self) -> None:
        ids = self._ids()

        self.assertEqual(ids[0], self.exam)
        self.assertNotIn(self.style, ids)

    def test_memories_already_in_the_prompt_or_just_offered_step_aside(self) -> None:
        ids = self._ids(exclude_ids={self.exam}, recently_offered={self.past})

        self.assertEqual(ids[0], self.films)
        self.assertNotIn(self.exam, ids)
        self.assertEqual(ids[-1], self.past)

    def test_the_source_tells_the_model_it_is_optional(self) -> None:
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}):
            [source] = _might_fit_sources(CHAT, USER_ID, [])

        self.assertIn("Use at most one, only if it fits", source["content"])
        self.assertIn("old black-and-white films", source["content"])


if __name__ == "__main__":
    unittest.main()
