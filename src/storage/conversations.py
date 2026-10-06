from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from agent.shared.clock import utc_now

from .conversation_threads import _delete_threads_only_from
from .database import ENGINE
from .schema import (
    user_profiles,
    agent_memory_embeddings,
    agent_memory_reviews,
    agent_self_notes,
    agent_open_questions,
    agent_context_snapshots,
    agent_jobs,
    agent_conversations,
    agent_message_feedback,
    agent_memories,
    agent_memory_evidence,
    agent_trace_steps,
    agent_traces,
    agent_usage_events,
    draft_profiles,
    memory_processing_leases,
    memory_processing_states,
    memory_operation_applications,
    conversation_states,
    thread_operation_applications,
)
from .utils import (
    _isoformat_utc,
    _owned_update_values,
    _protect_messages,
    _require_user_id,
    _unprotect_messages,
)

def save_draft(draft: dict[str, Any], user_id: str | None = None) -> None:
    owner_id = _require_user_id(user_id, "draft")
    payload = {
        "id": draft["id"],
        "user_id": owner_id,
        "status": draft["status"],
        "submission_json": draft["submission"],
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(draft_profiles.c.user_id).where(draft_profiles.c.id == draft["id"])
        ).mappings().first()
        if existing:
            if existing["user_id"] != owner_id:
                raise ValueError("draft belongs to a different user")
            connection.execute(
                draft_profiles.update()
                .where(draft_profiles.c.id == draft["id"], draft_profiles.c.user_id == owner_id)
                .values(**_owned_update_values(payload, "user_id"), updated_at=func.now())
            )
        else:
            connection.execute(draft_profiles.insert().values(**payload))


def get_draft(draft_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    owner_id = _require_user_id(user_id, "draft")
    statement = select(draft_profiles).where(
        draft_profiles.c.id == draft_id,
        draft_profiles.c.user_id == owner_id,
    )

    with ENGINE.begin() as connection:
        row = connection.execute(statement).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "submission": row["submission_json"],
    }


def save_conversation(conversation: dict[str, Any], user_id: str | None = None) -> None:
    conversation_user_id = _require_user_id(
        user_id or conversation.get("user_id"),
        "conversation",
    )
    payload = {
        "id": conversation["id"],
        "user_id": conversation_user_id,
        "status": conversation["status"],
        "agent_provider": conversation.get("agent_provider"),
        "agent_model": conversation.get("agent_model"),
        "agent_mode": conversation.get("agent_mode") or "know_me",
        "agent_tone": conversation.get("agent_tone") or "auto",
        "agent_name": conversation.get("agent_name"),
        "agent_voice": conversation.get("agent_voice"),
        "agent_style_source_id": conversation.get("agent_style_source_id"),
        "messages_json": _protect_messages(conversation_user_id, conversation["messages"]),
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_conversations.c.user_id).where(
                agent_conversations.c.id == conversation["id"]
            )
        ).mappings().first()
        if existing:
            if existing["user_id"] != conversation_user_id:
                raise ValueError("conversation belongs to a different user")
            connection.execute(
                agent_conversations.update()
                .where(
                    agent_conversations.c.id == conversation["id"],
                    agent_conversations.c.user_id == conversation_user_id,
                )
                .values(**_owned_update_values(payload, "user_id"), updated_at=func.now())
            )
        else:
            connection.execute(agent_conversations.insert().values(**payload))


# Chats from before the voice setting were named for a voice; keep it so nothing changes for them.
_LEGACY_NAME_VOICES = {"Annie": "female", "Kabir": "male"}


def _stored_voice(row: Any) -> str:
    return row.get("agent_voice") or _LEGACY_NAME_VOICES.get(str(row.get("agent_name") or ""), "neutral")


def get_conversation(conversation_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    owner_id = _require_user_id(user_id, "conversation")
    statement = select(agent_conversations).where(
        agent_conversations.c.id == conversation_id,
        agent_conversations.c.user_id == owner_id,
    )

    with ENGINE.begin() as connection:
        row = connection.execute(statement).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "agent_provider": row.get("agent_provider"),
        "agent_model": row.get("agent_model"),
        "agent_mode": row.get("agent_mode") or "know_me",
        "agent_tone": row.get("agent_tone") or "auto",
        "agent_name": row.get("agent_name"),
        "agent_voice": _stored_voice(row),
        "agent_style_source_id": row.get("agent_style_source_id"),
        "archived_at": _isoformat_utc(row.get("archived_at")),
        "messages": _unprotect_messages(row["user_id"], row["messages_json"]),
    }


def set_conversation_archived(conversation_id: str, user_id: str, archived: bool) -> tuple[bool, str | None]:
    """(found, archived_at). Leaves updated_at alone, so archiving never moves a chat in History."""
    owner_id = _require_user_id(user_id, "conversation")
    with ENGINE.begin() as connection:
        result = connection.execute(
            agent_conversations.update()
            .where(
                agent_conversations.c.id == conversation_id,
                agent_conversations.c.user_id == owner_id,
            )
            .values(archived_at=utc_now() if archived else None)
            .returning(agent_conversations.c.archived_at)
        ).first()
    if result is None:
        return False, None
    return True, _isoformat_utc(result[0])


def list_conversation_ids(user_id: str) -> set[str]:
    """Just the ids of a user's chats, without loading their messages."""
    owner_id = _require_user_id(user_id, "conversation list")
    with ENGINE.begin() as connection:
        return set(
            connection.execute(
                select(agent_conversations.c.id).where(agent_conversations.c.user_id == owner_id)
            ).scalars().all()
        )


def list_conversation_user_ids(*, with_profile: bool = False) -> list[str]:
    """Every user who has at least one chat (for maintenance scripts). with_profile keeps only
    users who signed up, which leaves out eval and test accounts."""
    statement = (
        select(agent_conversations.c.user_id)
        .where(agent_conversations.c.user_id.is_not(None))
        .distinct()
    )
    if with_profile:
        statement = statement.where(
            agent_conversations.c.user_id.in_(select(user_profiles.c.user_id))
        )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).scalars().all()
    return sorted(str(user_id) for user_id in rows)


def list_conversations(user_id: str | None = None) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "conversation list")
    statement = (
        select(agent_conversations)
        .where(agent_conversations.c.user_id == owner_id)
        .order_by(agent_conversations.c.updated_at.desc())
    )

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()

    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "status": row["status"],
            "agent_provider": row.get("agent_provider"),
            "agent_model": row.get("agent_model"),
            "agent_mode": row.get("agent_mode") or "know_me",
            "agent_tone": row.get("agent_tone") or "auto",
            "agent_name": row.get("agent_name"),
            "agent_voice": _stored_voice(row),
            "agent_style_source_id": row.get("agent_style_source_id"),
            "archived_at": _isoformat_utc(row.get("archived_at")),
            "messages": _unprotect_messages(row["user_id"], row["messages_json"]),
            "created_at": _isoformat_utc(row["created_at"]),
            "updated_at": _isoformat_utc(row["updated_at"]),
        }
        for row in rows
    ]


def delete_conversation(conversation_id: str, user_id: str | None = None) -> bool:
    owner_id = _require_user_id(user_id, "conversation")
    statement = select(agent_conversations.c.id).where(
        agent_conversations.c.id == conversation_id,
        agent_conversations.c.user_id == owner_id,
    )

    with ENGINE.begin() as connection:
        existing = connection.execute(statement).first()
        if not existing:
            return False

        connection.execute(
            agent_usage_events.delete().where(
                agent_usage_events.c.conversation_id == conversation_id,
                agent_usage_events.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_message_feedback.delete().where(
                agent_message_feedback.c.conversation_id == conversation_id,
                agent_message_feedback.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_context_snapshots.delete().where(
                agent_context_snapshots.c.conversation_id == conversation_id,
                agent_context_snapshots.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_trace_steps.delete().where(
                agent_trace_steps.c.conversation_id == conversation_id,
                agent_trace_steps.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_traces.delete().where(
                agent_traces.c.conversation_id == conversation_id,
                agent_traces.c.user_id == owner_id,
            )
        )
        connection.execute(
            memory_processing_leases.delete().where(
                memory_processing_leases.c.conversation_id == conversation_id,
                memory_processing_leases.c.user_id == owner_id,
            )
        )
        connection.execute(
            memory_processing_states.delete().where(
                memory_processing_states.c.conversation_id == conversation_id,
                memory_processing_states.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_jobs.delete().where(
                agent_jobs.c.conversation_id == conversation_id,
                agent_jobs.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_open_questions.delete().where(
                agent_open_questions.c.conversation_id == conversation_id,
                agent_open_questions.c.user_id == owner_id,
            )
        )
        connection.execute(
            agent_self_notes.delete().where(
                agent_self_notes.c.conversation_id == conversation_id,
                agent_self_notes.c.user_id == owner_id,
            )
        )
        memory_ids = [
            row[0]
            for row in connection.execute(
                select(agent_memory_evidence.c.memory_id).where(
                    agent_memory_evidence.c.conversation_id == conversation_id,
                    agent_memory_evidence.c.user_id == owner_id,
                )
            ).all()
        ]
        connection.execute(
            agent_memory_evidence.delete().where(
                agent_memory_evidence.c.conversation_id == conversation_id,
                agent_memory_evidence.c.user_id == owner_id,
            )
        )
        if memory_ids:
            # Memories left without any evidence go, with their vectors and reviews.
            orphan_ids = [
                row[0]
                for row in connection.execute(
                    select(agent_memories.c.id).where(
                        agent_memories.c.user_id == owner_id,
                        agent_memories.c.id.in_(memory_ids),
                        ~agent_memories.c.id.in_(
                            select(agent_memory_evidence.c.memory_id).where(
                                agent_memory_evidence.c.user_id == owner_id
                            )
                        ),
                    )
                ).all()
            ]
            if orphan_ids:
                for table in (agent_memory_embeddings, agent_memory_reviews):
                    connection.execute(
                        table.delete().where(
                            table.c.user_id == owner_id, table.c.memory_id.in_(orphan_ids)
                        )
                    )
                connection.execute(
                    agent_memories.delete().where(
                        agent_memories.c.user_id == owner_id, agent_memories.c.id.in_(orphan_ids)
                    )
                )
        connection.execute(
            memory_operation_applications.delete().where(
                memory_operation_applications.c.conversation_id == conversation_id,
                memory_operation_applications.c.user_id == owner_id,
            )
        )
        # Topics that lived only in this chat go with it, so Omi never brings them up again.
        _delete_threads_only_from(connection, owner_id, {conversation_id})
        for table in (thread_operation_applications, conversation_states):
            connection.execute(
                table.delete().where(
                    table.c.conversation_id == conversation_id, table.c.user_id == owner_id
                )
            )
        connection.execute(
            agent_conversations.delete().where(
                agent_conversations.c.id == conversation_id,
                agent_conversations.c.user_id == owner_id,
            )
        )
    # Like memories, vibe lines lose the proof that came from this chat (and go if none is left).
    from .vibe_cards import drop_vibe_proof_from_conversation

    drop_vibe_proof_from_conversation(owner_id, conversation_id)
    return True
