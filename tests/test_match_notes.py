"""Match notes: what the model is shown, what code keeps of its answer, and when there is enough."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.matching.notes import (
    MATCH_NOTES_SYSTEM_PROMPT, MAX_PER_KIND, message_parts, notes_input, notes_readiness, own_messages, validate_notes,
)


def conversation(conversation_id: str, lines: list[tuple[str, str, str]], **extra) -> dict:
    return {"id": conversation_id, "messages": [{"role": role, "content": text, "created_at": at} for role, text, at in lines], **extra}


CHATS = [
    conversation("c1", [
        ("user", "arsenal lost again lol", "2026-11-01T21:00:00+00:00"),
        ("assistant", "ouch", "2026-11-01T21:00:05+00:00"),
        ("user", "  fifa   tonight after 9 ", "2026-11-02T20:00:00+00:00"),
    ]),
    conversation("c2", [("user", "secret", "2026-11-03T10:00:00+00:00")], temporary=True),
    conversation("c3", [("user", "", "2026-11-03T10:00:00+00:00"), ("user", "hate people who cancel last minute", "2026-11-04T09:00:00+00:00")]),
]


class OwnMessagesTest(unittest.TestCase):
    def test_only_the_users_own_lines_outside_temporary_chats_oldest_first(self) -> None:
        messages = own_messages(CHATS)
        self.assertEqual([(m["conversation_id"], m["message_index"], m["text"]) for m in messages], [
            ("c1", 0, "arsenal lost again lol"), ("c1", 2, "fifa tonight after 9"), ("c3", 1, "hate people who cancel last minute"),
        ])
        self.assertEqual(len(own_messages(CHATS, after="2026-11-02T20:00:00+00:00")), 1)

    def test_a_long_history_is_read_in_parts_and_only_the_newest_parts(self) -> None:
        messages = [{"conversation_id": "c", "message_index": i, "sent_at": f"2026-11-01T00:{i % 60:02d}:00+00:00", "text": "x" * 400} for i in range(200)]
        parts = message_parts(messages)
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[-1][-1]["message_index"], 199)
        self.assertTrue(all(sum(len(m["text"]) for m in part) <= 12000 for part in parts))
        self.assertEqual(message_parts(messages[:3]), [messages[:3]])

    def test_the_model_sees_numbers_and_days_never_ids(self) -> None:
        text, numbered = notes_input("Aarav", "2026-11-05", [{"id": "n1", "kind": "loves", "text": "Follows Arsenal.", "evidence": []}], own_messages(CHATS))
        pack = json.loads(text)
        self.assertEqual(pack["messages"][1], {"n": 2, "day": "2026-11-02", "text": "fifa tonight after 9"})
        self.assertEqual(pack["current_notes"], [{"id": "n1", "kind": "loves", "text": "Follows Arsenal."}])
        self.assertEqual(numbered[3]["conversation_id"], "c3")
        self.assertNotIn("c3", text)
        self.assertIn("- cannot_stand:", MATCH_NOTES_SYSTEM_PROMPT)
        self.assertNotIn("KINDS", MATCH_NOTES_SYSTEM_PROMPT)


class ValidateTest(unittest.TestCase):
    def setUp(self) -> None:
        _, self.numbered = notes_input("Aarav", "2026-11-05", [], own_messages(CHATS))
        self.current = [{"id": "n1", "kind": "loves", "text": "Follows Arsenal.", "evidence": [{"conversation_id": "c0", "message_index": 4, "sent_at": "2026-10-20T10:00:00+00:00"}]}]

    def test_a_note_needs_a_known_kind_a_sentence_and_real_messages(self) -> None:
        notes = validate_notes({"notes": [
            {"kind": "loves", "text": "Plays FIFA at night.", "from": [2]},
            {"kind": "zodiac", "text": "A Leo.", "from": [1]},
            {"kind": "humour", "text": "", "from": [1]},
            {"kind": "humour", "text": "Laughs at his own team losing.", "from": [99, "1", True]},  # no real message
            {"kind": "cannot_stand", "text": "Cannot stand last-minute cancelling.", "from": [3, 3]},
            {"kind": "LOVES", "text": "plays fifa at night.", "from": [2]},  # the same sentence again
            "junk",
        ]}, [], self.numbered)
        self.assertEqual([(n["id"], n["kind"], n["text"]) for n in notes], [("n1", "loves", "Plays FIFA at night."), ("n2", "cannot_stand", "Cannot stand last-minute cancelling.")])
        self.assertEqual(notes[1]["evidence"], [{"conversation_id": "c3", "message_index": 1, "sent_at": "2026-11-04T09:00:00+00:00"}])
        self.assertEqual(validate_notes("not json", [], self.numbered), [])

    def test_a_kept_note_keeps_its_id_and_proof_and_gains_new_proof(self) -> None:
        notes = validate_notes({"notes": [
            {"kind": "loves", "text": "Follows Arsenal and suffers with them.", "from": [1], "keeps": "n1"},
            {"kind": "loves", "text": "A second claim on the same note.", "keeps": "n1"},  # a note is kept once
            {"kind": "rhythm", "text": "Free after nine at night.", "from": [2], "keeps": "n9"},  # unknown id: a new note
        ]}, self.current, self.numbered)
        self.assertEqual([n["id"] for n in notes], ["n1", "n2"])
        self.assertEqual([e["conversation_id"] for e in notes[0]["evidence"]], ["c0", "c1"])
        # Kept without new messages: the old proof is enough.
        kept = validate_notes({"notes": [{"kind": "loves", "text": "Follows Arsenal.", "keeps": "n1"}]}, self.current, self.numbered)
        self.assertEqual((kept[0]["id"], len(kept[0]["evidence"])), ("n1", 1))
        # Left out by the model: gone.
        self.assertEqual(validate_notes({"notes": []}, self.current, self.numbered), [])

    def test_bounded_per_kind(self) -> None:
        raw = {"notes": [{"kind": "loves", "text": f"Thing {i}.", "from": [1]} for i in range(MAX_PER_KIND + 3)]}
        self.assertEqual(len(validate_notes(raw, [], self.numbered)), MAX_PER_KIND)


class ReadinessTest(unittest.TestCase):
    def test_enough_is_six_notes_over_three_core_kinds(self) -> None:
        def notes(*kinds: str) -> list[dict]:
            return [{"id": f"n{i}", "kind": kind, "text": "x", "evidence": [{}]} for i, kind in enumerate(kinds)]

        self.assertFalse(notes_readiness(None)["ready"])
        self.assertFalse(notes_readiness(notes("loves", "loves", "loves", "humour", "humour", "humour"))["ready"])  # two kinds
        self.assertFalse(notes_readiness(notes("loves", "humour", "wants", "gives", "rhythm"))["ready"])  # five notes
        self.assertFalse(notes_readiness(notes("loves", "humour", "views", "views", "moment", "cannot_stand"))["ready"])  # two core kinds
        ready = notes_readiness(notes("loves", "loves", "humour", "wants", "moment", "views"))
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["missing_core"], ("gives", "rhythm"))


class RebuildTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_rebuild_reads_only_new_messages_and_a_broken_answer_keeps_the_old_notes(self) -> None:
        store: dict = {}
        writer = AsyncMock(return_value={"notes": [{"kind": "loves", "text": "Plays FIFA at night.", "from": [2]}]})
        with (
            patch("storage.get_match_notes", lambda user_id: store.get(user_id)),
            patch("storage.set_match_notes", lambda user_id, stored: store.__setitem__(user_id, stored)),
            patch("storage.list_conversations", lambda user_id: CHATS),
            patch("storage.get_user_profile", lambda user_id: {"display_name": "Aarav Shah"}),
            patch("agent.providers.write_match_notes", writer),
        ):
            from agent.matching.notes import rebuild_due, rebuild_match_notes

            self.assertFalse(rebuild_due("u"))  # three messages, eight needed
            self.assertEqual((await rebuild_match_notes("u"))["status"], "nothing_new")
            first = await rebuild_match_notes("u", force=True)
            self.assertEqual((first["status"], first["notes"]), ("rebuilt", 1))
            self.assertEqual(json.loads(writer.await_args.args[0])["name"], "Aarav")
            self.assertEqual(store["u"]["covered_upto"], "2026-11-04T09:00:00+00:00")
            # Nothing new since: no call.
            self.assertEqual((await rebuild_match_notes("u", force=True))["status"], "nothing_new")
            self.assertEqual(writer.await_count, 1)
            # New messages and a broken answer: the old notes stay and the messages are read again next time.
            CHATS.append(conversation("c4", [("user", "new line", "2026-11-06T09:00:00+00:00")]))
            writer.return_value = {}
            try:
                again = await rebuild_match_notes("u", force=True)
            finally:
                CHATS.pop()
            self.assertEqual((again["status"], again["notes"]), ("kept", 1))
            self.assertEqual(store["u"]["notes"][0]["text"], "Plays FIFA at night.")
            self.assertEqual(store["u"]["covered_upto"], "2026-11-04T09:00:00+00:00")


def friend_chat(n: int = 12) -> list[dict]:
    """A stored upload: the user's lines are role "user", the friend's are role "other", with old dates."""
    out = []
    for i in range(n):
        out.append({"role": "other", "speaker": "Riya", "content": f"friend line {i}", "imported": True, "created_at": f"2025-03-{i + 1:02d}T20:00:00+05:30"})
        out.append({"role": "user", "content": f"my line {i} about treks", "imported": True, "created_at": f"2025-03-{i + 1:02d}T20:05:00+05:30"})
    return out


class UploadTest(unittest.IsolatedAsyncioTestCase):
    """A shared chat is read into the notes once, on its own, and its proof goes when it is deleted."""

    def setUp(self) -> None:
        from storage import reset_db, save_context_source, save_conversation, save_user_profile

        reset_db()
        save_user_profile("ua", "male", "female", display_name="Aman Verma", city="Pune")
        save_conversation({"id": "omi-chat", "status": "active", "messages": [{"role": "user", "content": f"to omi {i}", "created_at": f"2026-11-{i + 1:02d}T10:00:00+00:00"} for i in range(9)]}, "ua")
        self.source = save_context_source({"user_id": "ua", "conversation_id": "omi-chat", "source_type": "whatsapp_chat", "title": "Riya", "content": "x", "metadata": {}})["id"]
        save_conversation({"id": "hidden-1", "status": "active", "import_source_id": self.source, "messages": friend_chat()}, "ua")

    def test_a_shared_chat_is_kept_apart_from_the_chats_with_omi(self) -> None:
        from storage import list_conversations

        chats = list_conversations("ua")
        self.assertEqual({m["conversation_id"] for m in own_messages(chats)}, {"omi-chat"})
        shared = own_messages(chats, uploads=True)
        self.assertEqual(({m["conversation_id"] for m in shared}, len(shared)), ({"hidden-1"}, 12))  # only the user's own side

    async def test_it_is_read_once_as_a_friend_chat_and_does_not_move_the_date_mark(self) -> None:
        from agent.matching.notes import add_upload_to_notes, rebuild_match_notes
        from storage import get_match_notes

        async def writer(text: str, **_: object) -> dict:
            sent = json.loads(text)
            kept = [{"kind": note["kind"], "text": note["text"], "keeps": note["id"]} for note in sent["current_notes"]]
            return {"notes": kept + [{"kind": "loves" if sent["source"] == "friend_chat" else "rhythm", "text": f"From {sent['source']}.", "from": [1, 2]}]}

        calls = AsyncMock(side_effect=writer)
        with patch("agent.providers.write_match_notes", calls):
            self.assertEqual((await rebuild_match_notes("ua"))["status"], "rebuilt")       # nine lines to Omi
            mark = get_match_notes("ua")["covered_upto"]
            first = await add_upload_to_notes("ua", self.source)
            self.assertEqual((first["status"], first["notes"], first["new_messages"]), ("rebuilt", 2, 12))
            self.assertEqual(json.loads(calls.await_args.args[0])["source"], "friend_chat")
            self.assertEqual((await add_upload_to_notes("ua", self.source))["status"], "already_read")
            self.assertEqual(calls.await_count, 2)
            stored = get_match_notes("ua")
            self.assertEqual((stored["uploads"], stored["covered_upto"]), ([self.source], mark))  # the old dates of the upload moved nothing
            self.assertEqual({e["conversation_id"] for n in stored["notes"] if n["kind"] == "loves" for e in n["evidence"]}, {"hidden-1"})
            # The daily pass keeps the list of uploads it did not read itself.
            self.assertEqual((await rebuild_match_notes("ua", force=True))["status"], "nothing_new")
            self.assertEqual(get_match_notes("ua")["uploads"], [self.source])
            self.assertEqual((await add_upload_to_notes("ua", "no-such-upload"))["status"], "nothing_new")

    async def test_deleting_the_upload_takes_its_proof_and_lets_it_be_read_again(self) -> None:
        from agent.matching.notes import add_upload_to_notes
        from storage import get_match_notes, set_match_notes
        from storage.conversations import delete_import_conversations

        proof_here = {"conversation_id": "hidden-1", "message_index": 1}
        proof_omi = {"conversation_id": "omi-chat", "message_index": 0}
        set_match_notes("ua", {"version": 1, "covered_upto": None, "messages_seen": 0, "uploads": [self.source], "notes": [
            {"id": "n1", "kind": "loves", "text": "Only from the shared chat.", "evidence": [proof_here]},
            {"id": "n2", "kind": "humour", "text": "From both.", "evidence": [proof_omi, proof_here]},
            {"id": "n3", "kind": "rhythm", "text": "Only from Omi.", "evidence": [proof_omi]},
        ]})
        self.assertEqual(delete_import_conversations("ua", self.source), 1)
        stored = get_match_notes("ua")
        self.assertEqual([(n["id"], len(n["evidence"])) for n in stored["notes"]], [("n2", 1), ("n3", 1)])
        self.assertEqual(stored["uploads"], [])
        with patch("agent.providers.write_match_notes", AsyncMock(return_value={})):
            self.assertEqual((await add_upload_to_notes("ua", self.source))["status"], "nothing_new")  # the chat is gone


if __name__ == "__main__":
    unittest.main()
