"""Touchpoints pair one person's memories with the other's most similar ones from the stored
embeddings. Only active, standard memories that are not how-to-talk rules take part, names are
taken out, each memory is used once, and a touchpoint may back a reason only when both memories
carry the matching purpose."""

import unittest
from datetime import UTC, datetime

import storage
from agent.matching.touchpoints import Touchpoint, memory_text, pair_touchpoints, touchpoints

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)
A, B = "touch-a", "touch-b"


def _memory(user_id: str, key: str, statement: str, *, purposes=("matching",), sensitivity="standard", kind="semantic", about=(), status="active") -> dict:
    memory = storage.create_agent_memory(
        {
            "user_id": user_id,
            "kind": kind,
            "purposes": list(purposes),
            "key": key,
            "value": statement,
            "statement": statement,
            "status": status,
            "sensitivity": sensitivity,
            "about": list(about),
            "confidence": 0.9,
            "importance": 0.6,
            "evidence": [{"conversation_id": f"chat-{user_id}", "message_index": 0, "exact_quote": statement, "observed_at": NOW.isoformat()}],
        }
    )
    return memory


def _embed(memory: dict, values: list[float], model: str = "bge-m3") -> None:
    storage.save_agent_memory_embedding(memory["id"], memory["user_id"], {"provider": "deepinfra", "model": model, "dimensions": len(values), "values": values})


class TouchpointsTest(unittest.TestCase):
    def setUp(self) -> None:
        storage.reset_db()
        for user_id in (A, B):
            storage.save_conversation({"id": f"chat-{user_id}", "status": "active", "messages": [{"role": "user", "content": "hi", "created_at": NOW.isoformat()}]}, user_id)

    def test_pairs_the_closest_memories_once_each_strongest_first(self) -> None:
        walk_a = _memory(A, "walks", "Walks the Fergusson loop with Arjun after work most days", about=["Arjun"])
        quiet_a = _memory(A, "quiet", "Wants a friend she can sit quietly with", purposes=("profile",))
        fast_a = _memory(A, "fasts", "Fasts on Thursdays")
        walk_b = _memory(B, "walk", "Tries to walk 6 km every evening since moving")
        walk_b2 = _memory(B, "walk2", "Walked to the office on Monday")
        quiet_b = _memory(B, "tiring", "Finds it tiring to keep a conversation going all evening")
        _embed(walk_a, [1.0, 0.0, 0.0]); _embed(quiet_a, [0.0, 1.0, 0.0]); _embed(fast_a, [0.0, 0.0, 1.0])
        _embed(walk_b, [0.95, 0.05, 0.0]); _embed(walk_b2, [0.9, 0.1, 0.0]); _embed(quiet_b, [0.1, 0.9, 0.0])

        points = pair_touchpoints(A, B)
        self.assertEqual([(p.memory_a, p.memory_b) for p in points], [(walk_a["id"], walk_b["id"]), (quiet_a["id"], quiet_b["id"])])
        self.assertEqual(points[0].text_a, "Walks the Fergusson loop with [name] after work most days")
        self.assertTrue(points[0].reason_ok)
        self.assertFalse(points[1].reason_ok)  # quiet_a is a profile memory, not matching
        self.assertGreater(points[0].similarity, points[1].similarity)
        self.assertEqual(points[0].as_dict()["a"], points[0].text_a)

    def test_private_retracted_and_how_to_talk_memories_never_take_part(self) -> None:
        money_a = _memory(A, "money", "Broke with her college group over money", sensitivity="sensitive")
        gone_a = _memory(A, "gone", "Used to run every morning", status="retracted")
        rule_a = _memory(A, "rule", "Reply in English", kind="procedural", purposes=("personalization",))
        fine_a = _memory(A, "fine", "Loves street cricket on Sundays")
        money_b = _memory(B, "money", "Lent money to a friend, never got it back")
        cricket_b = _memory(B, "cricket", "Plays gully cricket every Sunday")
        for memory, values in ((money_a, [1.0, 0.0]), (gone_a, [0.0, 1.0]), (rule_a, [1.0, 0.0]), (fine_a, [0.0, 1.0]), (money_b, [1.0, 0.0]), (cricket_b, [0.0, 1.0])):
            _embed(memory, values)
        points = pair_touchpoints(A, B)
        self.assertEqual([(p.memory_a, p.memory_b) for p in points], [(fine_a["id"], cricket_b["id"])])

    def test_below_the_floor_or_another_model_gives_nothing(self) -> None:
        a = _memory(A, "a", "Likes trains"); b = _memory(B, "b", "Hates mornings")
        _embed(a, [1.0, 0.0]); _embed(b, [0.3, 0.95])
        self.assertEqual(pair_touchpoints(A, B), [])
        c = _memory(A, "c", "Likes trains too"); d = _memory(B, "d", "Loves trains")
        _embed(c, [1.0, 0.0]); _embed(d, [1.0, 0.0], model="other")
        self.assertEqual(pair_touchpoints(A, B), [])

    def test_limit_and_pure_function(self) -> None:
        memories_a = [{"id": f"a{i}", "statement": f"a {i}", "purposes": ["matching"], "sensitivity": "standard"} for i in range(8)]
        memories_b = [{"id": f"b{i}", "statement": f"b {i}", "purposes": ["matching"], "sensitivity": "standard"} for i in range(8)]
        vec = lambda i: {"provider": "p", "model": "m", "dimensions": 8, "values": [1.0 if j == i else 0.0 for j in range(8)]}  # noqa: E731
        emb_a = [{"memory_id": f"a{i}", **vec(i)} for i in range(8)]
        emb_b = [{"memory_id": f"b{i}", **vec(i)} for i in range(8)]
        points = touchpoints(memories_a, emb_a, memories_b, emb_b, limit=3)
        self.assertEqual(len(points), 3)
        self.assertTrue(all(isinstance(p, Touchpoint) and p.similarity == 1.0 for p in points))
        self.assertEqual(memory_text({"statement": "Met Priya Sharma and Priya at Baner", "about": ["Priya Sharma", "Baner"]}), "Met [name] and Priya at [name]")


if __name__ == "__main__":
    unittest.main()
