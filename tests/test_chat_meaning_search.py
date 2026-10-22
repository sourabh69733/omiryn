"""Meaning search over chat chunks: indexed once, found by meaning, merged with word matches."""

import os
import unittest
from unittest.mock import patch

from agent.memory_engine.search import chat_chunks, index_chat, search_chats_hybrid
from storage import delete_conversation, reset_db, save_conversation, set_user_timezone
from storage.chat_embeddings import decode_vector, encode_vector, list_chunk_embeddings

USER_ID = "meaning-search-user"
# A tiny fake model: each text becomes a vector over a few concepts.
CONCEPTS = {"wedding": ("engage", "shaadi", "wedding", "relationship", "married"), "work": ("review", "task", "office", "work"), "food": ("biryani", "lunch", "food")}


def _fake_vector(text: str) -> list[float]:
    text = text.lower()
    vector = [float(sum(word in text for word in words)) for words in CONCEPTS.values()]
    return vector if any(vector) else [0.01, 0.01, 0.01]


async def _fake_embeddings(*, inputs, **_):
    return [_fake_vector(text) for text in inputs]


async def _fake_query(text, **_):
    return {"provider": "deepinfra", "model": "BAAI/bge-m3", "dimensions": 3, "values": _fake_vector(text)}


def _message(role: str, text: str, day: int, speaker: str | None = None) -> dict:
    return {"role": role, "content": text, "created_at": f"2026-10-{day:02d}T10:00:00+00:00", **({"speaker": speaker} if speaker else {})}


class MeaningSearchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "deepinfra:BAAI/bge-m3"})
        self.env.start()
        set_user_timezone(USER_ID, "Asia/Kolkata")
        messages = [
            _message("other", "big news, my engagement is fixed for december", 2, "Farheen"),
            _message("user", "omg congrats!! when is the shaadi", 2),
            _message("other", "wedding in march, engagement first", 2, "Farheen"),
            _message("user", "so happy for you", 2),
        ]
        messages += [_message("user" if n % 2 else "other", f"review task number {n} at the office", 10, None if n % 2 else "Farheen") for n in range(1, 12)]
        save_conversation({"id": "upload", "status": "active", "import_source_id": "src", "messages": messages}, USER_ID)

    def tearDown(self) -> None:
        self.env.stop()

    async def _index(self) -> int:
        with patch("agent.memory_engine.search.chat_index.provider_embeddings", _fake_embeddings):
            return await index_chat(USER_ID, "upload")

    async def test_chunks_are_indexed_once(self) -> None:
        self.assertEqual(await self._index(), 4)
        self.assertEqual(await self._index(), 0)
        self.assertEqual(len(list_chunk_embeddings(USER_ID, "deepinfra", "BAAI/bge-m3")), 4)

    async def test_meaning_finds_what_words_cannot(self) -> None:
        await self._index()
        with patch("agent.memory_engine.search.chat_search.embed_memory_query", _fake_query):
            hits = await search_chats_hybrid(USER_ID, "her relationship status")
        self.assertTrue(any("engagement is fixed" in line for hit in hits for line in hit.lines))

    async def test_without_vectors_it_is_the_word_search(self) -> None:
        with patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "off"}):
            hits = await search_chats_hybrid(USER_ID, "engagement december")
            self.assertTrue(any("engagement is fixed" in line for hit in hits for line in hit.lines))
            self.assertEqual(await search_chats_hybrid(USER_ID, "her relationship status"), [])

    async def test_deleting_the_chat_deletes_its_vectors(self) -> None:
        await self._index()
        delete_conversation("upload", USER_ID)
        self.assertEqual(list_chunk_embeddings(USER_ID, "deepinfra", "BAAI/bge-m3"), [])

    def test_chunks_and_vectors_round_trip(self) -> None:
        chunks = chat_chunks([_message("user", "hi", 1), _message("assistant", "hey", 1), _message("user", " ", 1)])
        self.assertEqual(chunks, [(0, 0, 2, "User: hi\nOmi: hey")])
        self.assertEqual(decode_vector(encode_vector([0.5, -1.25])), [0.5, -1.25])


if __name__ == "__main__":
    unittest.main()
