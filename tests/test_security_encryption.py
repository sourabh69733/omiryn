import base64
import os
import unittest
from unittest.mock import patch

from scripts.encrypt_existing_sensitive_data import encrypt_existing_sensitive_data
from sqlalchemy import select

from security.encryption import (
    EncryptionError,
    decrypt_json,
    decrypt_text,
    encrypt_json,
    encrypt_text,
    encryption_enabled,
    is_encrypted_blob,
    maybe_encrypt_json,
)
from storage import (
    ENGINE,
    agent_conversations,
    conversation_context_sources,
    get_conversation,
    list_context_sources,
    reset_db,
    save_context_source,
    save_conversation,
)


class EncryptionServiceTest(unittest.TestCase):
    def test_encrypts_and_decrypts_json_for_same_user(self) -> None:
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": key}):
            encrypted = encrypt_json("user-a", {"messages": [{"content": "private chat"}]})

            self.assertTrue(is_encrypted_blob(encrypted))
            self.assertNotIn("private chat", str(encrypted))
            self.assertEqual(
                decrypt_json("user-a", encrypted),
                {"messages": [{"content": "private chat"}]},
            )

    def test_wrong_user_cannot_decrypt(self) -> None:
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": key}):
            encrypted = encrypt_text("user-a", "private chat")

            with self.assertRaises(EncryptionError):
                decrypt_text("user-b", encrypted)

    def test_plaintext_values_still_read_during_migration(self) -> None:
        self.assertEqual(decrypt_text("user-a", "legacy text"), "legacy text")
        self.assertEqual(decrypt_json("user-a", [{"content": "legacy"}]), [{"content": "legacy"}])

    def test_maybe_encrypt_noops_when_key_is_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(encryption_enabled())
            self.assertEqual(maybe_encrypt_json("user-a", {"content": "legacy"}), {"content": "legacy"})


class StorageEncryptionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_conversation_messages_are_encrypted_at_rest(self) -> None:
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": key}):
            save_conversation(
                {
                    "id": "conversation-a",
                    "status": "active",
                    "messages": [{"role": "user", "content": "my private message"}],
                },
                "user-a",
            )

            with ENGINE.begin() as connection:
                raw_messages = connection.execute(
                    select(agent_conversations.c.messages_json).where(
                        agent_conversations.c.id == "conversation-a"
                    )
                ).scalar_one()

            self.assertIsInstance(raw_messages, dict)
            self.assertNotIn("my private message", str(raw_messages))
            conversation = get_conversation("conversation-a", "user-a")
            self.assertEqual(
                conversation["messages"],
                [{"role": "user", "content": "my private message"}],
            )

    def test_context_content_is_encrypted_at_rest(self) -> None:
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": key}):
            save_conversation(
                {"id": "conversation-a", "status": "active", "messages": []},
                "user-a",
            )
            created = save_context_source(
                {
                    "conversation_id": "conversation-a",
                    "source_type": "manual_notes",
                    "title": "Private note",
                    "content": "my private context note",
                }
            )

            with ENGINE.begin() as connection:
                raw_content = connection.execute(
                    select(conversation_context_sources.c.content).where(
                        conversation_context_sources.c.id == created["id"]
                    )
                ).scalar_one()

            self.assertIsInstance(raw_content, str)
            self.assertNotIn("my private context note", raw_content)
            sources = list_context_sources("conversation-a", "user-a")
            self.assertEqual(sources[0]["content"], "my private context note")

    def test_backfill_script_encrypts_existing_plaintext_rows(self) -> None:
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

        with patch.dict("os.environ", {}, clear=True):
            save_conversation(
                {
                    "id": "conversation-a",
                    "status": "active",
                    "messages": [{"role": "user", "content": "legacy private message"}],
                },
                "user-a",
            )
            save_context_source(
                {
                    "user_id": "user-a",
                    "conversation_id": "conversation-a",
                    "source_type": "manual_notes",
                    "title": "Legacy note",
                    "content": "legacy private context",
                }
            )
            with ENGINE.begin() as connection:
                self.assertEqual(
                    connection.execute(select(conversation_context_sources.c.content)).scalar_one(),
                    "legacy private context",
                )

        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": key}):
            result = encrypt_existing_sensitive_data()

        self.assertEqual(result["conversation_encrypted"], 1)
        self.assertEqual(result["context_encrypted"], 1)
        with ENGINE.begin() as connection:
            raw_messages = connection.execute(
                select(agent_conversations.c.messages_json).where(
                    agent_conversations.c.id == "conversation-a"
                )
            ).scalar_one()
            raw_content = connection.execute(select(conversation_context_sources.c.content)).scalar_one()

        self.assertNotIn("legacy private message", str(raw_messages))
        self.assertNotIn("legacy private context", raw_content)
        with patch.dict("os.environ", {"ENCRYPTION_MASTER_KEY": key}):
            self.assertEqual(
                get_conversation("conversation-a", "user-a")["messages"][0]["content"],
                "legacy private message",
            )
            self.assertEqual(
                list_context_sources("conversation-a", "user-a")[0]["content"],
                "legacy private context",
            )
