from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from .database import ENGINE
from .schema import (
    agent_behavior_rules,
    agent_context_snapshots,
    agent_conversations,
    agent_message_feedback,
    agent_trace_steps,
    agent_traces,
    agent_usage_events,
    app_events,
    conversation_context_sources,
    data_point_extraction_debug,
    data_point_feedback,
    data_requests,
    draft_profiles,
    feedback_submissions,
    profile_facts,
    public_leads,
    user_profiles,
    whatsapp_chunks,
    whatsapp_imports,
    whatsapp_messages,
    whatsapp_people,
    whatsapp_style_profiles,
)


def delete_user_private_data(user_id: str, email: str | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "user_id": user_id,
        "deleted": {},
        "profile_photo_file_names": [],
    }
    with ENGINE.begin() as connection:
        profile = connection.execute(
            select(user_profiles).where(user_profiles.c.user_id == user_id)
        ).mappings().first()
        summary["profile_photo_file_names"] = _profile_photo_file_names(profile)

        for table in (
            data_point_feedback,
            profile_facts,
            agent_behavior_rules,
            data_point_extraction_debug,
            whatsapp_style_profiles,
            whatsapp_people,
            whatsapp_chunks,
            whatsapp_messages,
            whatsapp_imports,
            conversation_context_sources,
            agent_message_feedback,
            agent_context_snapshots,
            agent_trace_steps,
            agent_traces,
            agent_usage_events,
            agent_conversations,
            draft_profiles,
            app_events,
            feedback_submissions,
            data_requests,
            user_profiles,
        ):
            result = connection.execute(table.delete().where(table.c.user_id == user_id))
            summary["deleted"][table.name] = int(result.rowcount or 0)

        if email:
            result = connection.execute(
                public_leads.delete().where(func.lower(public_leads.c.contact) == email.lower())
            )
            summary["deleted"][public_leads.name] = int(result.rowcount or 0)

    return summary


def _profile_photo_file_names(profile: Any) -> list[str]:
    if not profile:
        return []
    names: list[str] = []
    for value in profile["profile_photo_file_names"] or []:
        if value:
            names.append(str(value))
    single = profile["profile_photo_file_name"]
    if single:
        names.append(str(single))
    return sorted(set(names))
