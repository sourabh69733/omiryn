import base64
import os
import unittest
from unittest.mock import patch

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
