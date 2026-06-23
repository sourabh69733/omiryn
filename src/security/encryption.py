from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


ENCRYPTED_BLOB_VERSION = 1
ENCRYPTED_BLOB_ALGORITHM = "AES-256-GCM"


class EncryptionError(ValueError):
    pass


def encryption_enabled() -> bool:
    return bool(os.getenv("ENCRYPTION_MASTER_KEY", "").strip())


def encrypt_text(user_id: str | None, value: str) -> dict[str, str | int]:
    return _encrypt_bytes(user_id, value.encode("utf-8"))


def decrypt_text(user_id: str | None, value: Any) -> str:
    if not is_encrypted_blob(value):
        return "" if value is None else str(value)
    return _decrypt_bytes(user_id, value).decode("utf-8")


def encrypt_json(user_id: str | None, value: Any) -> dict[str, str | int]:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _encrypt_bytes(user_id, payload)


def decrypt_json(user_id: str | None, value: Any) -> Any:
    if not is_encrypted_blob(value):
        return value
    payload = _decrypt_bytes(user_id, value)
    return json.loads(payload.decode("utf-8"))


def maybe_encrypt_text(user_id: str | None, value: str) -> str | dict[str, str | int]:
    return encrypt_text(user_id, value) if encryption_enabled() else value


def maybe_encrypt_json(user_id: str | None, value: Any) -> Any:
    return encrypt_json(user_id, value) if encryption_enabled() else value


def is_encrypted_blob(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("v") == ENCRYPTED_BLOB_VERSION
        and value.get("alg") == ENCRYPTED_BLOB_ALGORITHM
        and isinstance(value.get("nonce"), str)
        and isinstance(value.get("ciphertext"), str)
    )


def _encrypt_bytes(user_id: str | None, value: bytes) -> dict[str, str | int]:
    nonce = os.urandom(12)
    key = _user_key(user_id)
    ciphertext = AESGCM(key).encrypt(nonce, value, _aad(user_id))
    return {
        "v": ENCRYPTED_BLOB_VERSION,
        "alg": ENCRYPTED_BLOB_ALGORITHM,
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }


def _decrypt_bytes(user_id: str | None, value: dict[str, Any]) -> bytes:
    try:
        nonce = _b64decode(str(value["nonce"]))
        ciphertext = _b64decode(str(value["ciphertext"]))
        return AESGCM(_user_key(user_id)).decrypt(nonce, ciphertext, _aad(user_id))
    except (InvalidTag, KeyError, TypeError, ValueError) as error:
        raise EncryptionError("Could not decrypt protected data.") from error


def _user_key(user_id: str | None) -> bytes:
    user_scope = str(user_id or "anonymous").encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=user_scope,
        info=b"omiryn:user-data:v1",
    ).derive(_master_key())


def _master_key() -> bytes:
    raw = os.getenv("ENCRYPTION_MASTER_KEY", "").strip()
    if not raw:
        raise EncryptionError("ENCRYPTION_MASTER_KEY is not configured.")
    try:
        key = base64.urlsafe_b64decode(_padded_b64(raw))
    except ValueError as error:
        raise EncryptionError("ENCRYPTION_MASTER_KEY must be base64 encoded.") from error
    if len(key) != 32:
        raise EncryptionError("ENCRYPTION_MASTER_KEY must decode to 32 bytes.")
    return key


def _aad(user_id: str | None) -> bytes:
    return f"omiryn:user:{user_id or 'anonymous'}".encode("utf-8")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(_padded_b64(value))


def _padded_b64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
