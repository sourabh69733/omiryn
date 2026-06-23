import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - keeps tests usable before deps install
    load_dotenv = None

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

from agent.providers import (
    AgentProviderError,
    agent_runtime_status,
    extract_profile,
)
from admin.routes import ADMIN_STATIC_DIR, router as admin_router
from agent.context import (
    STYLE_CONTEXT_SOURCE_TYPES,
    build_profile_extraction_context_sources,
    build_reply_context_sources,
    selected_style_source_exists,
)
from agent.feedback import normalize_message_feedback
from agent.memory import (
    capture_deep_profile_facts_from_conversation,
    should_run_deep_profile_fact_extraction,
)
from agent.orchestrator import run_agent_turn
from auth import CurrentUser, current_user, public_auth_config
from ingestion.whatsapp import WHATSAPP_IMPORT_MAX_CHARS, build_whatsapp_style_summary
from matching import AgePreference, Dealbreaker, MatchProfile, score_match
from storage import (
    delete_context_source,
    delete_user_context_source,
    delete_conversation as storage_delete_conversation,
    get_conversation as storage_get_conversation,
    get_draft as storage_get_draft,
    get_user_profile,
    init_db,
    list_context_sources,
    list_conversations as storage_list_conversations,
    list_profile_facts,
    list_user_context_sources,
    list_agent_usage_events,
    list_agent_message_feedback,
    save_context_source,
    save_conversation,
    save_draft,
    save_agent_message_feedback,
    save_user_profile,
    summarize_agent_usage,
)

STATIC_DIR = Path(__file__).parent / "static"
APP_SHELL_HEADERS = {"Cache-Control": "no-store"}
AgentMode = Literal["know_me", "coach_me", "match_me", "talk_like_me"]
AgentTone = Literal["auto", "casual", "warm", "formal", "direct", "playful"]
AgentMessageFeedbackRating = Literal["good", "off", "bad", "harmful"]
ContextSourceType = Literal[
    "llm_profile",
    "chat_export",
    "manual_notes",
    "whatsapp_chat",
    "friend_style",
]
WhatsappStyleKind = Literal["user_style", "friend_style"]
Gender = Literal["man", "woman", "non_binary", "prefer_not_to_say"]
InterestedIn = Literal["men", "women", "everyone"]
DEFAULT_AGENT_COUNTRY = os.getenv("AGENT_DEFAULT_COUNTRY", "India")
DEFAULT_AGENT_TIMEZONE = os.getenv("AGENT_DEFAULT_TIMEZONE", "Asia/Kolkata")
LLM_CONTEXT_IMPORT_PROMPT = """I am using Omiryn to build a private personal profile about myself.

Please create a concise, privacy-safe self-profile about me based only on what you know from our past chats.
Focus on me as a person, not on my dating life. Include relationship details only if I clearly discussed them before.

Return sections:
1. Basic background and life context, only if known
2. Personality traits and temperament
3. Core values, priorities, and beliefs
4. Interests, hobbies, routines, and lifestyle patterns
5. Communication style and thinking style
6. Goals, ambitions, and current focus areas
7. Strengths, recurring challenges, and stress patterns
8. Preferences, dislikes, boundaries, and sensitivities
9. Important unknowns Omiryn should ask me

Rules:
- Do not invent facts.
- Mark uncertain points as uncertain.
- Do not infer romantic status, past relationships, sexual preferences, attraction patterns, or ideal partner unless explicitly known.
- Avoid exposing names, phone numbers, addresses, or private third-party details.
- Keep it under 1000 words.
"""

app = FastAPI(
    title="Omiryn API",
    version="0.1.0",
    description="AI-assisted matchmaking platform API.",
)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, object]):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
app.mount(
    "/admin/static",
    NoCacheStaticFiles(directory=ADMIN_STATIC_DIR),
    name="admin-static",
)
app.include_router(admin_router)


@app.on_event("startup")
def startup() -> None:
    init_db()


class SourcedString(BaseModel):
    value: str
    source: Literal["user_stated", "inferred", "unknown"] = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1)


class SourcedList(BaseModel):
    values: list[str] = Field(default_factory=list)
    source: Literal["user_stated", "inferred", "unknown"] = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1)


class AgentProfileSubmission(BaseModel):
    agent_provider: str = Field(examples=["chatgpt"])
    agent_user_reference: str | None = None
    display_name: str | None = None
    age: int | None = Field(default=None, ge=18, le=100)
    gender: SourcedString = Field(default_factory=lambda: SourcedString(value="unknown"))
    interested_in: SourcedString = Field(default_factory=lambda: SourcedString(value="unknown"))
    city: SourcedString = Field(default_factory=lambda: SourcedString(value="unknown"))
    relationship_intent: SourcedString = Field(
        default_factory=lambda: SourcedString(value="unknown")
    )
    values: SourcedList = Field(default_factory=SourcedList)
    lifestyle: SourcedList = Field(default_factory=SourcedList)
    communication_style: SourcedString = Field(default_factory=lambda: SourcedString(value="unknown"))
    family_expectations: SourcedString = Field(default_factory=lambda: SourcedString(value="unknown"))
    children_preference: SourcedString = Field(default_factory=lambda: SourcedString(value="unknown"))
    dealbreakers: SourcedList = Field(default_factory=SourcedList)
    soft_preferences: SourcedList = Field(default_factory=SourcedList)
    summary: str = ""
    extraction_warnings: list[str] = Field(default_factory=list)


class DraftProfile(BaseModel):
    id: str
    status: Literal["draft", "approved", "deleted"]
    submission: AgentProfileSubmission


class DraftPatch(BaseModel):
    display_name: str | None = None
    gender: str | None = None
    interested_in: str | None = None
    city: str | None = None
    relationship_intent: str | None = None
    communication_style: str | None = None
    family_expectations: str | None = None
    children_preference: str | None = None
    values: list[str] | None = None
    lifestyle: list[str] | None = None
    dealbreakers: list[str] | None = None
    soft_preferences: list[str] | None = None
    summary: str | None = None


class AgentConversation(BaseModel):
    id: str
    status: Literal["active", "extracted"] = "active"
    agent_provider: str | None = None
    agent_model: str | None = None
    agent_mode: AgentMode = "know_me"
    agent_tone: AgentTone = "auto"
    agent_name: str | None = Field(default=None, max_length=40)
    agent_style_source_id: str | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)


class AgentConversationCreate(BaseModel):
    agent_model: str | None = None
    agent_mode: AgentMode = "know_me"
    agent_tone: AgentTone = "auto"
    agent_name: str | None = Field(default=None, max_length=40)
    agent_style_source_id: str | None = None


class AgentConversationSettings(BaseModel):
    agent_model: str | None = None
    agent_mode: AgentMode | None = None
    agent_tone: AgentTone | None = None
    agent_name: str | None = Field(default=None, max_length=40)
    agent_style_source_id: str | None = None


class AgentConversationSummary(BaseModel):
    id: str
    status: Literal["active", "extracted"]
    agent_provider: str | None = None
    agent_model: str | None = None
    agent_mode: AgentMode = "know_me"
    agent_tone: AgentTone = "auto"
    agent_name: str | None = None
    agent_style_source_id: str | None = None
    message_count: int = 0
    user_message_count: int = 0
    context_source_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class UserMessage(BaseModel):
    message: str = Field(min_length=1)


class AgentMessageFeedbackCreate(BaseModel):
    rating: AgentMessageFeedbackRating
    reason: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=1000)


class ContextSourceCreate(BaseModel):
    source_type: ContextSourceType = "llm_profile"
    title: str = Field(default="Imported context", min_length=1, max_length=120)
    content: str = Field(min_length=20, max_length=50000)


class ContextSourceAttachmentsUpdate(BaseModel):
    source_ids: list[str] = Field(default_factory=list)


class WhatsappChatImportCreate(BaseModel):
    title: str = Field(default="WhatsApp speaking style", min_length=1, max_length=120)
    user_sender: str | None = Field(default=None, max_length=120)
    style_name: str | None = Field(default=None, max_length=120)
    style_kind: WhatsappStyleKind = "user_style"
    content: str = Field(min_length=50, max_length=WHATSAPP_IMPORT_MAX_CHARS)


class DatingBasics(BaseModel):
    gender: Gender
    interested_in: InterestedIn


class UserProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    gender: Gender
    interested_in: InterestedIn


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/agent/status")
def agent_status() -> dict[str, object]:
    return agent_runtime_status()


@app.get("/api/auth/config")
def auth_config() -> dict[str, object]:
    return {
        **public_auth_config(),
        "profile_debug_data_enabled": _profile_debug_data_enabled(),
    }


@app.get("/api/auth/me")
async def auth_me(user: CurrentUser | None = Depends(current_user)) -> dict[str, str | None]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return _auth_user_payload(user)


@app.get("/api/me/dating-basics")
async def get_dating_basics(
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    profile = get_user_profile(user.id)
    return {
        "complete": bool(profile and profile.get("gender") and profile.get("interested_in")),
        "profile": profile,
    }


@app.put("/api/me/dating-basics")
async def put_dating_basics(
    payload: DatingBasics,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    existing_profile = get_user_profile(user.id)
    profile = save_user_profile(
        user.id,
        payload.gender,
        payload.interested_in,
        (existing_profile or {}).get("display_name") or user.display_name,
    )
    return {"complete": True, "profile": profile}


@app.get("/api/me/profile")
async def get_me_profile(
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    profile = _profile_with_auth_defaults(get_user_profile(user.id), user)
    sources = list_user_context_sources(user.id)
    facts = list_profile_facts(user.id)
    response = {
        "user": _auth_user_payload(user),
        "profile": profile,
        "learned_facts": facts,
        "learned_fact_groups": _group_profile_facts(facts),
        "style_sources": [
            _context_source_summary(source)
            for source in sources
            if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
        ],
        "memory_sources": [
            _context_source_summary(source)
            for source in sources
            if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
        ],
    }
    if _profile_debug_data_enabled():
        response["raw_internal_data_points"] = _raw_profile_data_points(facts)
    return response


@app.put("/api/me/profile")
async def put_me_profile(
    payload: UserProfilePatch,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    profile = save_user_profile(
        user.id,
        payload.gender,
        payload.interested_in,
        payload.display_name.strip() if payload.display_name else None,
    )
    return {"profile": profile}


@app.get("/api/me/profile-facts")
async def get_me_profile_facts(
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    facts = list_profile_facts(user.id)
    return {"facts": facts, "groups": _group_profile_facts(facts)}


@app.get("/api/agent/usage")
async def agent_usage(
    conversation_id: str | None = None,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    # Groq limits are API-key level, so the main dashboard should be app-wide.
    # Per-session usage remains scoped in /api/agent/conversations/{id}/usage.
    return {
        "summary": summarize_agent_usage(conversation_id, None),
        "events": list_agent_usage_events(conversation_id, None),
        "limits": _configured_usage_limits(),
    }


@app.get("/api/agent/conversations/{conversation_id}/usage")
async def conversation_agent_usage(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    return {
        "summary": summarize_agent_usage(conversation_id, _user_id(user)),
        "events": list_agent_usage_events(conversation_id, _user_id(user)),
        "limits": _configured_usage_limits(),
    }


@app.get("/api/context-import-prompt")
def context_import_prompt() -> dict[str, str]:
    return {"prompt": LLM_CONTEXT_IMPORT_PROMPT}


@app.get("/api/agent/conversations/{conversation_id}/context-sources")
async def get_conversation_context_sources(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    sources = list_context_sources(conversation_id, _user_id(user))
    user_sources = _reusable_context_sources(list_user_context_sources(_user_id(user)))
    reusable_source_ids = {str(source["id"]) for source in user_sources}
    attached_sources = _attached_context_sources(sources, reusable_source_ids)
    attached_ids = _attached_context_source_ids(sources)
    return {
        "count": len(attached_sources),
        "sources": [
            _context_source_summary(source, attached=True)
            for source in attached_sources
        ],
        "available_sources": [
            _context_source_summary(source, attached=source["id"] in attached_ids)
            for source in user_sources
        ],
    }


@app.get("/api/agent/conversations/{conversation_id}/tone")
async def get_conversation_tone(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    conversation = _get_existing_conversation(conversation_id, user)
    return {
        "selected_tone": conversation.agent_tone,
        "detected_tone": _detect_conversation_tone(
            conversation.messages,
            list_context_sources(conversation_id, _user_id(user)),
        ),
    }


@app.post("/api/agent/conversations/{conversation_id}/context-sources", status_code=201)
def create_conversation_context_source(
    conversation_id: str,
    payload: ContextSourceCreate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    source = save_context_source(
        {
            "user_id": _user_id(user),
            "conversation_id": conversation_id,
            "source_type": payload.source_type,
            "title": payload.title,
            "content": payload.content,
            "metadata": {"content_length": len(payload.content)},
        }
    )
    return _context_source_summary(source)


@app.delete("/api/agent/conversations/{conversation_id}/context-sources/{source_id}")
def delete_conversation_context_source(
    conversation_id: str,
    source_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    _get_existing_conversation(conversation_id, user)
    deleted = (
        delete_user_context_source(source_id, user.id)
        if user
        else delete_context_source(source_id, conversation_id, None)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Context source not found.")
    return {"source_id": source_id, "status": "deleted"}


@app.put("/api/agent/conversations/{conversation_id}/context-sources/attachments")
def update_conversation_context_attachments(
    conversation_id: str,
    payload: ContextSourceAttachmentsUpdate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    user_id = _user_id(user)
    requested_ids = list(dict.fromkeys(payload.source_ids))
    reusable_sources = _reusable_context_sources(list_user_context_sources(user_id))
    reusable_by_id = {str(source["id"]): source for source in reusable_sources}
    unknown_ids = [source_id for source_id in requested_ids if source_id not in reusable_by_id]
    if unknown_ids:
        raise HTTPException(status_code=404, detail="One or more saved context items were not found.")

    attached_sources = list_context_sources(conversation_id, user_id)
    for source_id in requested_ids:
        source = reusable_by_id[source_id]
        if _attached_context_source_by_original_id(attached_sources, source_id):
            continue
        save_context_source(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "source_type": source["source_type"],
                "title": source["title"],
                "content": source["content"],
                "metadata": {
                    **(source.get("metadata") or {}),
                    "original_source_id": source["id"],
                    "attached_from_conversation_id": source["conversation_id"],
                },
            }
        )

    for source in attached_sources:
        metadata = source.get("metadata") or {}
        original_source_id = metadata.get("original_source_id") if isinstance(metadata, dict) else None
        if original_source_id and original_source_id not in requested_ids:
            delete_context_source(str(source["id"]), conversation_id, user_id)

    sources = list_context_sources(conversation_id, user_id)
    user_sources = _reusable_context_sources(list_user_context_sources(user_id))
    reusable_source_ids = {str(source["id"]) for source in user_sources}
    attached_sources = _attached_context_sources(sources, reusable_source_ids)
    attached_ids = _attached_context_source_ids(sources)
    return {
        "count": len(attached_sources),
        "sources": [
            _context_source_summary(source, attached=True)
            for source in attached_sources
        ],
        "available_sources": [
            _context_source_summary(source, attached=source["id"] in attached_ids)
            for source in user_sources
        ],
    }


@app.post("/api/agent/conversations/{conversation_id}/whatsapp-import", status_code=201)
def create_whatsapp_context_source(
    conversation_id: str,
    payload: WhatsappChatImportCreate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    try:
        style_summary = build_whatsapp_style_summary(
            payload.content,
            user_sender=payload.user_sender,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    source = save_context_source(
        {
            "user_id": _user_id(user),
            "conversation_id": conversation_id,
            "source_type": "friend_style"
            if payload.style_kind == "friend_style"
            else "whatsapp_chat",
            "title": payload.title,
            "content": _whatsapp_style_context_content(
                style_summary.content,
                payload.style_kind,
                payload.style_name or payload.title,
            ),
            "metadata": {
                **style_summary.metadata,
                "style_kind": payload.style_kind,
                "style_name": payload.style_name,
            },
        }
    )
    return _context_source_summary(source)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@app.post("/api/agent/conversations", status_code=201)
async def create_agent_conversation(
    payload: AgentConversationCreate | None = None,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    conversation_id = str(uuid4())
    runtime = agent_runtime_status()
    selected_model = _normalize_selected_model(
        payload.agent_model if payload else None,
        runtime,
    )
    user_profile = _agent_user_context(user)
    persona = _agent_persona_for_profile(user_profile)
    agent_name = _normalize_agent_name(payload.agent_name if payload else None, persona)
    conversation = AgentConversation(
        id=conversation_id,
        agent_provider=str(runtime["provider"]),
        agent_model=selected_model,
        agent_mode=payload.agent_mode if payload else "know_me",
        agent_tone=payload.agent_tone if payload else "auto",
        agent_name=agent_name,
        agent_style_source_id=payload.agent_style_source_id if payload else None,
        messages=[
            {
                "role": "assistant",
                "content": _initial_agent_message({**persona, "name": agent_name}, user_profile),
            }
        ],
    )
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return conversation


@app.get("/api/agent/conversations")
async def list_agent_conversations(
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    conversations = storage_list_conversations(_user_id(user))
    summaries = []
    reusable_source_ids = {
        str(source["id"])
        for source in _reusable_context_sources(list_user_context_sources(_user_id(user)))
    }
    for conversation in conversations:
        messages = conversation["messages"]
        context_sources = list_context_sources(conversation["id"], _user_id(user))
        summaries.append(
            AgentConversationSummary(
                id=conversation["id"],
                status=conversation["status"],
                agent_provider=conversation["agent_provider"],
                agent_model=conversation["agent_model"],
                agent_mode=conversation["agent_mode"],
                agent_tone=conversation["agent_tone"],
                agent_name=conversation.get("agent_name")
                or _agent_persona_for_profile(_agent_user_context(user))["name"],
                agent_style_source_id=conversation["agent_style_source_id"],
                message_count=len(messages),
                user_message_count=sum(1 for message in messages if message.get("role") == "user"),
                context_source_count=len(_attached_context_sources(context_sources, reusable_source_ids)),
                created_at=conversation["created_at"],
                updated_at=conversation["updated_at"],
            ).model_dump()
        )
    return {"count": len(summaries), "conversations": summaries}


@app.get("/api/agent/conversations/{conversation_id}")
async def get_agent_conversation(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    return _get_existing_conversation(conversation_id, user)


@app.delete("/api/agent/conversations/{conversation_id}")
async def delete_agent_conversation(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    if not storage_delete_conversation(conversation_id, _user_id(user)):
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    return {"conversation_id": conversation_id, "status": "deleted"}


@app.patch("/api/agent/conversations/{conversation_id}/settings")
def update_agent_conversation_settings(
    conversation_id: str,
    payload: AgentConversationSettings,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id, user)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")

    runtime = agent_runtime_status()
    conversation.agent_provider = str(runtime["provider"])
    if payload.agent_model is not None:
        conversation.agent_model = _normalize_selected_model(payload.agent_model, runtime)
    if payload.agent_mode is not None:
        conversation.agent_mode = payload.agent_mode
    if payload.agent_tone is not None:
        conversation.agent_tone = payload.agent_tone
    if "agent_name" in payload.model_fields_set:
        conversation.agent_name = _normalize_agent_name(
            payload.agent_name,
            _agent_persona_for_profile(_agent_user_context(user)),
        )
    if "agent_style_source_id" in payload.model_fields_set:
        style_source_id = payload.agent_style_source_id or None
        _validate_style_source(conversation_id, style_source_id, _user_id(user))
        conversation.agent_style_source_id = style_source_id
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return conversation


@app.post("/api/agent/conversations/{conversation_id}/messages")
async def send_agent_message(
    conversation_id: str,
    payload: UserMessage,
    background_tasks: BackgroundTasks,
    user: CurrentUser | None = Depends(current_user),
) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id, user)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")

    try:
        turn = await run_agent_turn(
            conversation_id=conversation.id,
            messages=conversation.messages,
            user_text=payload.message,
            user_id=_user_id(user),
            user_profile=_agent_user_context(user),
            model=conversation.agent_model,
            agent_mode=conversation.agent_mode,
            agent_tone=conversation.agent_tone,
            agent_name=conversation.agent_name,
            style_source_id=conversation.agent_style_source_id,
        )
    except (AgentProviderError, Exception) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    conversation.messages = turn.messages
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    if should_run_deep_profile_fact_extraction(_user_id(user), conversation.messages, turn.quality_valid):
        background_tasks.add_task(
            capture_deep_profile_facts_from_conversation,
            conversation.id,
            user.id,
            conversation.messages,
            conversation.agent_model,
        )
    return conversation


@app.post("/api/agent/conversations/{conversation_id}/messages/{message_index}/feedback")
async def create_agent_message_feedback(
    conversation_id: str,
    message_index: int,
    payload: AgentMessageFeedbackCreate,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    conversation = _get_existing_conversation(conversation_id, user)
    if message_index < 0 or message_index >= len(conversation.messages):
        raise HTTPException(status_code=404, detail="Conversation message not found.")
    if conversation.messages[message_index].get("role") != "assistant":
        raise HTTPException(status_code=400, detail="Feedback can only be added to agent messages.")

    feedback = normalize_message_feedback(
        {
            "conversation_id": conversation_id,
            "user_id": _user_id(user),
            "message_index": message_index,
            "rating": payload.rating,
            "reason": payload.reason,
            "comment": payload.comment,
            "metadata": {
                "agent_provider": conversation.agent_provider,
                "agent_model": conversation.agent_model,
                "agent_name": conversation.agent_name,
            },
        }
    )
    return {"feedback": save_agent_message_feedback(feedback)}


@app.get("/api/agent/conversations/{conversation_id}/feedback")
async def get_agent_message_feedback(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, object]:
    _get_existing_conversation(conversation_id, user)
    feedback = list_agent_message_feedback(conversation_id, _user_id(user))
    return {"count": len(feedback), "feedback": feedback}


@app.post("/api/agent/conversations/{conversation_id}/extract")
async def extract_agent_conversation(
    conversation_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    conversation = _get_existing_conversation(conversation_id, user)
    try:
        raw_profile = await extract_profile(
            conversation.messages,
            conversation_id=conversation.id,
            model=conversation.agent_model,
            context_sources=_profile_extraction_context_sources(conversation.id, _user_id(user)),
        )
        submission = AgentProfileSubmission.model_validate(raw_profile)
        _apply_dating_basics(submission, user)
    except (AgentProviderError, ValueError, TypeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    draft_id = str(uuid4())
    save_draft(
        DraftProfile(id=draft_id, status="draft", submission=submission).model_dump(mode="json"),
        _user_id(user),
    )
    conversation.status = "extracted"
    save_conversation(conversation.model_dump(mode="json"), _user_id(user))
    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }


@app.post("/api/agent-submissions/profile", status_code=201)
async def submit_agent_profile(
    submission: AgentProfileSubmission,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    _apply_dating_basics(submission, user)
    draft_id = str(uuid4())
    save_draft(
        DraftProfile(id=draft_id, status="draft", submission=submission).model_dump(mode="json"),
        _user_id(user),
    )

    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }


@app.get("/api/drafts/{draft_id}")
async def get_draft(
    draft_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> DraftProfile:
    return _get_existing_draft(draft_id, user)


@app.patch("/api/drafts/{draft_id}")
async def update_draft(
    draft_id: str,
    patch: DraftPatch,
    user: CurrentUser | None = Depends(current_user),
) -> DraftProfile:
    draft = _get_existing_draft(draft_id, user)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft profiles can be edited.")

    data = draft.submission.model_copy(deep=True)

    if patch.display_name is not None:
        data.display_name = patch.display_name
    if patch.gender is not None:
        data.gender.value = patch.gender
        data.gender.source = "user_stated"
        data.gender.confidence = 1
    if patch.interested_in is not None:
        data.interested_in.value = patch.interested_in
        data.interested_in.source = "user_stated"
        data.interested_in.confidence = 1
    if patch.city is not None:
        data.city.value = patch.city
        data.city.source = "user_stated"
        data.city.confidence = 1
    if patch.relationship_intent is not None:
        data.relationship_intent.value = patch.relationship_intent
        data.relationship_intent.source = "user_stated"
        data.relationship_intent.confidence = 1
    if patch.communication_style is not None:
        data.communication_style.value = patch.communication_style
        data.communication_style.source = "user_stated"
        data.communication_style.confidence = 1
    if patch.family_expectations is not None:
        data.family_expectations.value = patch.family_expectations
        data.family_expectations.source = "user_stated"
        data.family_expectations.confidence = 1
    if patch.children_preference is not None:
        data.children_preference.value = patch.children_preference
        data.children_preference.source = "user_stated"
        data.children_preference.confidence = 1
    if patch.values is not None:
        data.values.values = patch.values
        data.values.source = "user_stated"
        data.values.confidence = 1
    if patch.lifestyle is not None:
        data.lifestyle.values = patch.lifestyle
        data.lifestyle.source = "user_stated"
        data.lifestyle.confidence = 1
    if patch.dealbreakers is not None:
        data.dealbreakers.values = patch.dealbreakers
        data.dealbreakers.source = "user_stated"
        data.dealbreakers.confidence = 1
    if patch.soft_preferences is not None:
        data.soft_preferences.values = patch.soft_preferences
        data.soft_preferences.source = "user_stated"
        data.soft_preferences.confidence = 1
    if patch.summary is not None:
        data.summary = patch.summary

    updated = DraftProfile(id=draft.id, status=draft.status, submission=data)
    save_draft(updated.model_dump(mode="json"), _user_id(user))
    return updated


@app.post("/api/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> DraftProfile:
    draft = _get_existing_draft(draft_id, user)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft profiles can be approved.")

    approved = DraftProfile(id=draft.id, status="approved", submission=draft.submission)
    save_draft(approved.model_dump(mode="json"), _user_id(user))
    return approved


@app.delete("/api/drafts/{draft_id}")
async def delete_draft(
    draft_id: str,
    user: CurrentUser | None = Depends(current_user),
) -> dict[str, str]:
    draft = _get_existing_draft(draft_id, user)
    save_draft(
        DraftProfile(id=draft.id, status="deleted", submission=draft.submission).model_dump(
            mode="json"
        ),
        _user_id(user),
    )
    return {"draft_id": draft_id, "status": "deleted"}


@app.get("/drafts/{draft_id}")
def draft_review_page(draft_id: str) -> FileResponse:
    _get_existing_draft(draft_id)
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@app.get("/matches")
def matches_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@app.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@app.get("/usage")
def usage_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@app.get("/api/demo/matches")
async def demo_matches(user: CurrentUser | None = Depends(current_user)) -> dict[str, object]:
    user = MatchProfile(
        id="user-demo",
        age=29,
        age_preference=AgePreference(min=26, max=33),
        relationship_intent="long_term",
        values=["family", "ambition", "emotional_stability"],
        lifestyle=["fitness", "travel", "balanced_work"],
        communication_style="direct",
        religion_importance="medium",
        family_involvement="medium",
        children_preference="wants_children",
        city="Bengaluru",
        dealbreakers=[Dealbreaker(type="smoking", severity="hard")],
        attributes=["vegetarian", "non_smoker"],
    )
    candidates = [
        MatchProfile(
            id="match-1",
            age=28,
            age_preference=AgePreference(min=28, max=34),
            relationship_intent="marriage",
            values=["family", "ambition", "kindness"],
            lifestyle=["fitness", "travel", "early_riser"],
            communication_style="direct",
            religion_importance="medium",
            family_involvement="medium",
            children_preference="wants_children",
            city="Bengaluru",
            dealbreakers=[Dealbreaker(type="heavy_drinking", severity="hard")],
            attributes=["non_smoker"],
        ),
        MatchProfile(
            id="match-2",
            age=31,
            age_preference=AgePreference(min=27, max=35),
            relationship_intent="long_term",
            values=["curiosity", "family", "calm"],
            lifestyle=["travel", "balanced_work", "reading"],
            communication_style="reflective",
            religion_importance="low",
            family_involvement="medium",
            children_preference="open",
            city="Mumbai",
            open_to_relocation=True,
            dealbreakers=[],
            attributes=["non_smoker"],
        ),
        MatchProfile(
            id="match-3",
            age=27,
            age_preference=AgePreference(min=29, max=36),
            relationship_intent="casual",
            values=["adventure", "independence"],
            lifestyle=["nightlife"],
            communication_style="spontaneous",
            city="Bengaluru",
            attributes=["smoking"],
        ),
    ]

    names = {
        "match-1": "Meera",
        "match-2": "Isha",
        "match-3": "Rhea",
    }

    return {
        "matches": [
            {
                "id": candidate.id,
                "name": names[candidate.id],
                "age": candidate.age,
                "city": candidate.city,
                "result": score_match(user, candidate),
            }
            for candidate in candidates
        ]
    }


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


def _raw_profile_data_points(facts: list[dict[str, object]]) -> list[dict[str, object]]:
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
        }
        for fact in facts
    ]


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


def _agent_persona_for_profile(profile: dict[str, object] | None) -> dict[str, str]:
    interested_in = str((profile or {}).get("interested_in") or "")
    if interested_in == "women":
        return {"name": "Annie", "presentation": "girl"}
    if interested_in == "men":
        return {"name": "Arjun", "presentation": "boy"}
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
    if name == "Arjun":
        return f"{greeting} Let's just talk normally first, no interview vibes."
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
