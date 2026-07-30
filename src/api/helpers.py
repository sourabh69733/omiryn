from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from agent.context_engine.context import (
    STYLE_CONTEXT_SOURCE_TYPES,
    build_profile_extraction_context_sources,
    build_reply_context_sources,
    selected_style_source_exists,
)
from security.auth import CurrentUser
from storage import (
    get_conversation as storage_get_conversation,
    get_draft as storage_get_draft,
    get_user_profile,
    list_profile_facts,
)

from .config import (
    DEFAULT_AGENT_COUNTRY,
    DEFAULT_AGENT_TIMEZONE,
    PROFILE_PHOTO_GCS_BUCKET,
    PROFILE_PHOTO_GCS_PREFIX,
    PROFILE_PHOTO_GCS_PUBLIC_BASE_URL,
    PROFILE_UPLOAD_DIR,
    gcs_storage,
)
from .models import AgentConversation, AgentProfileSubmission, DraftProfile, SourcedString, WhatsappStyleKind

logger = logging.getLogger(__name__)


def _compat_setting(name: str, default: object) -> object:
    main_module = sys.modules.get("api.main")
    if main_module is None:
        return default
    return getattr(main_module, name, default)


def _user_id(user: CurrentUser | None) -> str | None:
    return user.id if user else None


def _apply_dating_basics(submission: AgentProfileSubmission, user: CurrentUser | None) -> None:
    if not user:
        return
    profile = get_user_profile(user.id)
    if not profile:
        return
    if profile.get("gender"):
        submission.gender = SourcedString(
            value=profile["gender"],
            source="user_stated",
            confidence=1,
        )
    if profile.get("interested_in"):
        submission.interested_in = SourcedString(
            value=profile["interested_in"],
            source="user_stated",
            confidence=1,
        )


def _get_existing_draft(draft_id: str, user: CurrentUser | None = None) -> DraftProfile:
    draft = storage_get_draft(draft_id, _user_id(user))
    if not draft or draft["status"] == "deleted":
        raise HTTPException(status_code=404, detail="Draft profile not found.")
    return DraftProfile.model_validate(draft)


def _get_existing_conversation(
    conversation_id: str,
    user: CurrentUser | None = None,
) -> AgentConversation:
    conversation = storage_get_conversation(conversation_id, _user_id(user))
    if not conversation:
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    return AgentConversation.model_validate(conversation)


def _profile_extraction_context_sources(
    conversation_id: str,
    user_id: str | None = None,
) -> list[dict[str, object]]:
    return build_profile_extraction_context_sources(conversation_id, user_id)


def _smart_reply_context_sources(
    conversation_id: str,
    style_source_id: str | None,
    user_text: str,
    user_id: str | None = None,
) -> list[dict[str, object]]:
    return build_reply_context_sources(conversation_id, style_source_id, user_text, user_id)


def _validate_style_source(
    conversation_id: str,
    style_source_id: str | None,
    user_id: str | None = None,
) -> None:
    if selected_style_source_exists(conversation_id, style_source_id, user_id):
        return
    raise HTTPException(status_code=400, detail="Selected reply style was not found.")


def _whatsapp_style_context_content(
    summary_content: str,
    style_kind: WhatsappStyleKind,
    style_name: str,
) -> str:
    if style_kind == "user_style":
        return (
            "WhatsApp speaking-style context for the current user. Use this to adapt "
            "tone and pacing only.\n\n"
            f"{summary_content}"
        )

    return (
        f"Friend-style text profile: {style_name}.\n"
        "Use this only as a texting-style reference for rhythm, warmth, brevity, emoji "
        "habits, and phrasing patterns. Never claim to be this person, never imply this "
        "person is present, and never say they wrote or approved any message. If the user "
        "expects a different person or the selected sender seems wrong, ask which WhatsApp "
        "sender/style they want to use.\n\n"
        f"{summary_content}"
    )


def _detect_conversation_tone(
    messages: list[dict[str, str]],
    context_sources: list[dict[str, object]],
) -> dict[str, object]:
    user_text = " ".join(
        message.get("content", "")
        for message in messages[-20:]
        if message.get("role") == "user"
    ).lower()
    whatsapp_text = " ".join(
        str(source.get("content") or "")
        for source in context_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    ).lower()
    text = f"{user_text} {whatsapp_text}".strip()

    scores = {
        "casual": _tone_score(text, ["bro", "yaar", "haha", "lol", "hey", "btw", "gonna"]),
        "warm": _tone_score(text, ["thanks", "feel", "care", "kind", "calm", "understand"]),
        "formal": _tone_score(text, ["please", "regards", "would", "could", "kindly", "request"]),
        "direct": _tone_score(text, ["need", "tell", "clear", "exact", "simple", "short"]),
        "playful": _tone_score(text, ["haha", "lol", "fun", "joke", "crazy", "cool"]),
    }
    if not text:
        return {"tone": "warm", "confidence": 0.2, "reason": "Not enough conversation yet."}

    best_tone, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score == 0:
        return {"tone": "warm", "confidence": 0.35, "reason": "Defaulting to warm from limited tone signal."}
    confidence = min(0.9, round(0.45 + best_score * 0.12, 2))
    return {
        "tone": best_tone,
        "confidence": confidence,
        "reason": "Detected from recent messages and imported speaking-style context.",
    }


def _tone_score(text: str, markers: list[str]) -> int:
    return sum(text.count(marker) for marker in markers)


def _normalize_selected_model(model: str | None, runtime: dict[str, object]) -> str | None:
    available_models = runtime.get("available_models")
    if not isinstance(available_models, list):
        available_models = []
    model_names = [str(candidate) for candidate in available_models]
    selected = model or str(runtime.get("model") or "")
    if selected and (not model_names or selected in model_names):
        return selected
    if model_names:
        return model_names[0]
    return selected or None


def _sync_conversation_runtime(
    conversation: AgentConversation,
    runtime: dict[str, object],
) -> None:
    runtime_provider = str(runtime.get("provider") or "")
    available_models = runtime.get("available_models")
    if not isinstance(available_models, list):
        available_models = []
    model_names = [str(candidate) for candidate in available_models]
    if conversation.agent_provider != runtime_provider:
        conversation.agent_provider = runtime_provider
        conversation.agent_model = _normalize_selected_model(None, runtime)
        return
    if model_names and conversation.agent_model not in model_names:
        conversation.agent_model = _normalize_selected_model(None, runtime)


def _context_source_summary(
    source: dict[str, object],
    attached: bool | None = None,
) -> dict[str, object]:
    content = str(source.get("content") or "")
    summary = {
        "id": source["id"],
        "conversation_id": source["conversation_id"],
        "source_type": source["source_type"],
        "title": source["title"],
        "content_length": len(content),
        "preview": content[:240],
        "metadata": source.get("metadata") or {},
        "created_at": source["created_at"],
    }
    if attached is not None:
        summary["attached"] = attached
    return summary


def _group_profile_facts(facts: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for fact in facts:
        category = str(fact.get("category") or "other")
        groups.setdefault(category, []).append(fact)
    return groups


def _profile_with_auth_defaults(
    profile: dict[str, object] | None,
    user: CurrentUser,
) -> dict[str, object] | None:
    if not profile or profile.get("display_name") or not user.display_name:
        return profile
    return {**profile, "display_name": user.display_name}


def _profile_photo_public_url(object_name: str) -> str:
    public_base_url = str(
        _compat_setting("PROFILE_PHOTO_GCS_PUBLIC_BASE_URL", PROFILE_PHOTO_GCS_PUBLIC_BASE_URL)
        or ""
    )
    bucket = str(_compat_setting("PROFILE_PHOTO_GCS_BUCKET", PROFILE_PHOTO_GCS_BUCKET) or "")
    if public_base_url:
        return f"{public_base_url}/{quote(object_name)}"
    if bucket:
        return f"https://storage.googleapis.com/{bucket}/{quote(object_name)}"
    return f"/uploads/profile_photos/{object_name}"


def _store_profile_photo(
    *,
    user_id: str,
    content: bytes,
    content_type: str,
    extension: str,
) -> tuple[str, str]:
    bucket = str(_compat_setting("PROFILE_PHOTO_GCS_BUCKET", PROFILE_PHOTO_GCS_BUCKET) or "")
    prefix = str(_compat_setting("PROFILE_PHOTO_GCS_PREFIX", PROFILE_PHOTO_GCS_PREFIX) or "")
    if bucket:
        if gcs_storage is None:
            raise HTTPException(
                status_code=500,
                detail="GCP profile photo storage is configured but google-cloud-storage is not installed.",
            )
        object_prefix = f"{prefix}/" if prefix else ""
        object_name = f"{object_prefix}{user_id}/{uuid4().hex}{extension}"
        client = gcs_storage.Client()
        blob = client.bucket(bucket).blob(object_name)
        blob.upload_from_string(content, content_type=content_type)
        return _profile_photo_public_url(object_name), object_name

    filename = f"{user_id}-{uuid4().hex}{extension}"
    photo_path = PROFILE_UPLOAD_DIR / filename
    photo_path.write_bytes(content)
    return _profile_photo_public_url(filename), filename


def _delete_profile_photo_file_names(file_names: object) -> list[str]:
    if not isinstance(file_names, list):
        return []
    bucket = str(_compat_setting("PROFILE_PHOTO_GCS_BUCKET", PROFILE_PHOTO_GCS_BUCKET) or "")
    deleted: list[str] = []
    for raw_name in file_names:
        file_name = str(raw_name or "")
        if not file_name:
            continue
        if bucket:
            if _delete_gcs_profile_photo(file_name, bucket):
                deleted.append(file_name)
        elif _delete_local_profile_photo(file_name):
            deleted.append(file_name)
    return deleted


def _delete_gcs_profile_photo(object_name: str, bucket: str) -> bool:
    if gcs_storage is None:
        logger.warning("profile_photo.delete_gcs_unavailable object_name=%s", object_name)
        return False
    client = gcs_storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    try:
        blob.delete()
    except Exception as error:  # pragma: no cover - provider behavior varies
        logger.warning(
            "profile_photo.delete_gcs_failed object_name=%s error=%s",
            object_name,
            error,
        )
        return False
    return True


def _delete_local_profile_photo(file_name: str) -> bool:
    upload_root = PROFILE_UPLOAD_DIR.resolve()
    candidate = (upload_root / file_name).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError:
        return False
    if not candidate.is_file():
        return False
    candidate.unlink()
    return True


def _basic_profile_complete(profile: dict[str, object] | None) -> bool:
    return bool(
        profile
        and profile.get("display_name")
        and profile.get("age")
        and profile.get("gender")
        and profile.get("interested_in")
        and profile.get("city")
    )


def _clean_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _agent_user_context(user: CurrentUser | None) -> dict[str, object] | None:
    if not user:
        return {
            "country": DEFAULT_AGENT_COUNTRY,
            "location": DEFAULT_AGENT_COUNTRY,
            **_current_agent_time_context(),
        }
    profile = _profile_with_auth_defaults(get_user_profile(user.id), user) or {}
    city = str(profile.get("city") or _detected_user_city(user.id) or "").strip()
    display_name = str(profile.get("display_name") or user.display_name or "").strip()
    return {
        **profile,
        "user_id": user.id,
        "email": user.email,
        "display_name": display_name or None,
        "country": profile.get("country") or DEFAULT_AGENT_COUNTRY,
        "location": city or profile.get("location") or DEFAULT_AGENT_COUNTRY,
        **_current_agent_time_context(),
    }


def _detected_user_city(user_id: str) -> str | None:
    for fact in list_profile_facts(user_id):
        if fact.get("category") != "location" or fact.get("key") != "city":
            continue
        value = fact.get("value") or {}
        if isinstance(value, dict) and value.get("city"):
            return str(value["city"])
    return None


def _current_agent_time_context() -> dict[str, str]:
    timezone_name = DEFAULT_AGENT_TIMEZONE
    try:
        current = datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        timezone_name = "UTC"
        current = datetime.now(ZoneInfo("UTC"))
    return {
        "timezone": timezone_name,
        "current_date": current.strftime("%Y-%m-%d"),
        "current_time": current.strftime("%H:%M"),
        "current_weekday": current.strftime("%A"),
    }


def _auth_user_payload(user: CurrentUser) -> dict[str, str | None]:
    payload = {"id": user.id, "email": user.email}
    if user.display_name:
        payload["display_name"] = user.display_name
    if user.avatar_url:
        payload["avatar_url"] = user.avatar_url
    return payload


def _profile_debug_data_enabled() -> bool:
    return os.getenv("PROFILE_DEBUG_DATA_ENABLED", "false").lower() == "true"


def _latest_data_point_feedback_by_fact(
    feedback_items: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for item in feedback_items:
        fact_id = str(item.get("profile_fact_id") or "")
        if fact_id and fact_id not in latest:
            latest[fact_id] = item
    return latest


def _summarize_data_point_feedback(feedback_items: list[dict[str, object]]) -> dict[str, int]:
    summary = {"total": len(feedback_items), "agree": 0, "disagree": 0}
    for item in feedback_items:
        rating = str(item.get("rating") or "")
        if rating in summary:
            summary[rating] += 1
    return summary


def _profile_facts_with_feedback(
    facts: list[dict[str, object]],
    feedback_by_fact: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            **fact,
            "feedback": _data_point_feedback_summary_for_fact(
                feedback_by_fact.get(str(fact.get("id") or ""))
            ),
        }
        for fact in facts
    ]


def _raw_profile_data_points(
    facts: list[dict[str, object]],
    feedback_by_fact: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    feedback_by_fact = feedback_by_fact or {}
    return [
        {
            "id": fact.get("id"),
            "category": fact.get("category"),
            "key": fact.get("key"),
            "value": fact.get("value"),
            "confidence": fact.get("confidence"),
            "status": fact.get("status"),
            "source_kind": fact.get("source_kind"),
            "source_id": fact.get("source_id"),
            "used_for_matching": fact.get("used_for_matching"),
            "evidence_count": len(fact.get("evidence") or []),
            "visibility": fact.get("visibility"),
            "updated_at": fact.get("updated_at"),
            "feedback": _data_point_feedback_summary_for_fact(
                feedback_by_fact.get(str(fact.get("id") or ""))
            ),
        }
        for fact in facts
    ]


def _data_point_feedback_summary_for_fact(
    feedback: dict[str, object] | None,
) -> dict[str, object] | None:
    if not feedback:
        return None
    return {
        "rating": feedback.get("rating"),
        "reason": feedback.get("reason"),
        "comment": feedback.get("comment"),
        "updated_at": feedback.get("updated_at"),
    }


def _attached_context_source_ids(sources: list[dict[str, object]]) -> set[str]:
    attached_ids = set()
    for source in sources:
        metadata = source.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("original_source_id"):
            attached_ids.add(str(metadata["original_source_id"]))
    return attached_ids


def _attached_context_sources(
    sources: list[dict[str, object]],
    reusable_source_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    return [
        source
        for source in sources
        if isinstance(source.get("metadata"), dict)
        and source["metadata"].get("original_source_id")
        and (
            reusable_source_ids is None
            or str(source["metadata"].get("original_source_id")) in reusable_source_ids
        )
    ]


def _attached_context_source_by_original_id(
    sources: list[dict[str, object]],
    original_source_id: str,
) -> dict[str, object] | None:
    return next(
        (
            source
            for source in sources
            if isinstance(source.get("metadata"), dict)
            and source["metadata"].get("original_source_id") == original_source_id
        ),
        None,
    )


def _reusable_context_sources(sources: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        source
        for source in sources
        if not (
            isinstance(source.get("metadata"), dict)
            and source["metadata"].get("original_source_id")
        )
    ]


def _dedupe_context_sources(sources: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str, str]] = set()
    unique_sources: list[dict[str, object]] = []
    for source in sources:
        content = str(source.get("content") or "")
        key = (
            str(source.get("source_type") or ""),
            str(source.get("title") or "").strip().lower(),
            content.strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(source)
    return unique_sources


def _agent_persona_for_profile(profile: dict[str, object] | None) -> dict[str, str]:
    interested_in = str((profile or {}).get("interested_in") or "")
    if interested_in == "women":
        return {"name": "Annie", "presentation": "girl"}
    if interested_in == "men":
        return {"name": "Kabir", "presentation": "boy"}
    return {"name": "Mira", "presentation": "companion"}


def _normalize_agent_name(name: str | None, persona: dict[str, str]) -> str:
    cleaned = " ".join(str(name or "").strip().split())
    if not cleaned:
        return persona["name"]
    return cleaned[:40]


def _initial_agent_message(
    persona: dict[str, str],
    user_profile: dict[str, object] | None = None,
) -> str:
    name = persona["name"]
    display_name = str((user_profile or {}).get("display_name") or "").strip()
    greeting = f"Hey {display_name}, I'm {name}." if display_name else f"Hey, I'm {name}."
    if name == "Annie":
        return f"{greeting}"
    if name in {"Kabir", "Billy", "Aarav", "Ishaan", "Veer"}:
        return f"{greeting}"
    return f"{greeting}"


def _configured_usage_limits() -> dict[str, int | None]:
    return {
        "groq_rpd": _int_env("GROQ_RPD_LIMIT"),
        "groq_tpd": _int_env("GROQ_TPD_LIMIT"),
        "groq_rpm": _int_env("GROQ_RPM_LIMIT"),
        "groq_tpm": _int_env("GROQ_TPM_LIMIT"),
        "groq_input_tpd": _int_env("GROQ_INPUT_TPD_LIMIT"),
        "groq_output_tpd": _int_env("GROQ_OUTPUT_TPD_LIMIT"),
    }


def _int_env(name: str) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None
