"""Verifies private, user-owned persistence for canonical v3 memories."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import select

import storage
from agent.memory_engine.memories import retrieve_agent_memories_for_reply
from security.encryption import is_encrypted_blob
from storage.schema import agent_memories, agent_memory_evidence, agent_memory_reviews


USER_ID = "memory-v3-user"
CONVERSATION_ID = "memory-v3-conversation"
OBSERVED_AT = "2026-09-01T10:00:00Z"


@pytest.fixture(autouse=True)
def _database() -> None:
    storage.reset_db()
    storage.save_conversation(
        {
            "id": CONVERSATION_ID,
            "status": "active",
            "messages": [
                {
                    "role": "user",
                    "content": "I build a matchmaking product called Omiryn.",
                }
            ],
        },
        USER_ID,
    )


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_id": USER_ID,
        "kind": "semantic",
        "purposes": ["profile"],
        "key": "work.product",
        "value": {"name": "Omiryn", "role": "builder"},
        "allowed_uses": ["reply_context"],
        "confidence": 0.95,
        "importance": 0.7,
        "extractor": "background_cognition_v3",
        "extractor_model": "test-model",
        "evidence": [
            {
                "conversation_id": CONVERSATION_ID,
                "message_index": 0,
                "exact_quote": "I build a matchmaking product called Omiryn.",
                "observed_at": OBSERVED_AT,
            }
        ],
    }
    payload.update(changes)
    return payload


def test_create_and_read_memory_with_normalized_evidence() -> None:
    saved = storage.create_agent_memory(_payload())

    assert saved["kind"] == "semantic"
    assert saved["purposes"] == ["profile"]
    assert saved["value"] == {"name": "Omiryn", "role": "builder"}
    assert saved["schema_version"] == 3
    assert saved["created_at"] == saved["updated_at"]
    assert saved["evidence"][0]["conversation_id"] == CONVERSATION_ID
    assert saved["evidence"][0]["message_index"] == 0
    assert saved["evidence"][0]["observed_at"] == OBSERVED_AT
    assert storage.get_agent_memory(saved["id"], USER_ID) == saved
    assert storage.get_agent_memory(saved["id"], "another-user") is None


def test_storage_encrypts_memory_value_and_exact_quote() -> None:
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    with patch.dict(os.environ, {"ENCRYPTION_MASTER_KEY": key}):
        saved = storage.create_agent_memory(_payload())

        with storage.ENGINE.begin() as connection:
            memory_row = connection.execute(
                select(agent_memories).where(agent_memories.c.id == saved["id"])
            ).mappings().one()
            evidence_row = connection.execute(
                select(agent_memory_evidence).where(
                    agent_memory_evidence.c.memory_id == saved["id"]
                )
            ).mappings().one()

        assert is_encrypted_blob(memory_row["value_json"])
        assert is_encrypted_blob(json.loads(evidence_row["exact_quote"]))
        assert storage.get_agent_memory(saved["id"], USER_ID) == saved


def test_evidence_cannot_reference_another_users_conversation() -> None:
    storage.save_conversation(
        {
            "id": "foreign-conversation",
            "status": "active",
            "messages": [{"role": "user", "content": "Private detail"}],
        },
        "another-user",
    )
    evidence = [
        {
            "conversation_id": "foreign-conversation",
            "message_index": 0,
            "exact_quote": "Private detail",
            "observed_at": OBSERVED_AT,
        }
    ]

    with pytest.raises(ValueError, match="not found for this user"):
        storage.create_agent_memory(_payload(evidence=evidence))

    assert storage.list_agent_memories(USER_ID) == []


def test_delete_one_memory_removes_its_evidence_and_reply_access() -> None:
    saved = storage.create_agent_memory(_payload())
    storage.review_agent_memory(saved["id"], USER_ID, "agree")

    deleted = storage.delete_agent_memory(saved["id"], USER_ID)

    assert deleted
    assert storage.get_agent_memory(saved["id"], USER_ID) is None
    assert retrieve_agent_memories_for_reply(USER_ID, "What do I build?") == []
    with storage.ENGINE.begin() as connection:
        evidence = connection.execute(
            select(agent_memory_evidence).where(
                agent_memory_evidence.c.memory_id == saved["id"]
            )
        ).first()
        review = connection.execute(
            select(agent_memory_reviews).where(
                agent_memory_reviews.c.memory_id == saved["id"]
            )
        ).first()
    assert evidence is None
    assert review is None


def test_delete_one_memory_is_scoped_to_its_owner() -> None:
    saved = storage.create_agent_memory(_payload())

    deleted = storage.delete_agent_memory(saved["id"], "another-user")

    assert not deleted
    assert storage.get_agent_memory(saved["id"], USER_ID) is not None


def test_update_memory_permissions_immediately_changes_reply_eligibility() -> None:
    saved = storage.create_agent_memory(_payload())

    updated = storage.update_agent_memory_allowed_uses(
        saved["id"],
        USER_ID,
        ["matching"],
    )

    assert updated is not None
    assert updated["allowed_uses"] == ["matching"]
    assert retrieve_agent_memories_for_reply(USER_ID, "What do I build?") == []


def test_update_memory_permissions_is_scoped_to_its_owner() -> None:
    saved = storage.create_agent_memory(_payload())

    updated = storage.update_agent_memory_allowed_uses(
        saved["id"],
        "another-user",
        [],
    )

    assert updated is None
    assert storage.get_agent_memory(saved["id"], USER_ID)["allowed_uses"] == [
        "reply_context"
    ]


def test_user_deletion_removes_memory_and_evidence() -> None:
    saved = storage.create_agent_memory(_payload())
    storage.review_agent_memory(saved["id"], USER_ID, "agree")

    result = storage.delete_user_private_data(USER_ID)

    assert result["deleted"]["agent_memory_reviews"] == 1
    assert result["deleted"]["agent_memory_evidence"] == 1
    assert result["deleted"]["agent_memories"] == 1
    assert storage.get_agent_memory(saved["id"], USER_ID) is None


def test_conversation_deletion_removes_a_memory_with_no_remaining_evidence() -> None:
    saved = storage.create_agent_memory(_payload())

    assert storage.delete_conversation(CONVERSATION_ID, USER_ID)

    assert storage.get_agent_memory(saved["id"], USER_ID) is None


def test_conversation_deletion_preserves_memory_supported_elsewhere() -> None:
    second_conversation_id = "memory-v3-conversation-2"
    storage.save_conversation(
        {
            "id": second_conversation_id,
            "status": "active",
            "messages": [
                {
                    "role": "user",
                    "content": "Omiryn is the matchmaking product I am building.",
                }
            ],
        },
        USER_ID,
    )
    evidence = [
        {
            "conversation_id": CONVERSATION_ID,
            "message_index": 0,
            "exact_quote": "I build a matchmaking product called Omiryn.",
            "observed_at": OBSERVED_AT,
        },
        {
            "conversation_id": second_conversation_id,
            "message_index": 0,
            "exact_quote": "Omiryn is the matchmaking product I am building.",
            "observed_at": "2026-09-02T10:00:00Z",
        },
    ]
    saved = storage.create_agent_memory(_payload(evidence=evidence))

    assert storage.delete_conversation(CONVERSATION_ID, USER_ID)

    remaining = storage.get_agent_memory(saved["id"], USER_ID)
    assert remaining is not None
    assert [item["conversation_id"] for item in remaining["evidence"]] == [
        second_conversation_id
    ]
