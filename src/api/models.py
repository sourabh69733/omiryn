from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentMode = Literal["know_me", "coach_me", "match_me", "talk_like_me"]
AgentTone = Literal["auto", "casual", "warm", "formal", "direct", "playful"]
AgentMessageFeedbackRating = Literal["good", "off", "bad", "harmful"]
DataPointFeedbackRating = Literal["agree", "disagree"]
DataRequestType = Literal["export", "deletion"]
FeedbackCategory = Literal["feedback", "bug", "support", "privacy", "safety"]
CommunityChannel = Literal["whatsapp", "discord"]
AppEventName = Literal[
    "app_opened",
    "page_viewed",
    "chat_opened",
    "chat_started",
    "profile_saved",
    "memory_import_completed",
    "learned_signal_edited",
    "learned_signal_deleted",
    "learned_signal_confirmed",
    "learned_signal_rejected",
    "learned_signal_feedback_sent",
    "learned_signal_privacy_updated",
    "learned_signal_restored",
    "data_export_requested",
    "data_deletion_requested",
    "feedback_opened",
    "feedback_submitted",
    "community_invite_requested",
    "client_error",
]
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


class PublicEventCreate(BaseModel):
    session_id: str | None = Field(default=None, max_length=120)
    event_name: str = Field(max_length=80)
    path: str = Field(default="/", max_length=300)
    referrer: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublicLeadCreate(BaseModel):
    session_id: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=120)
    contact: str = Field(max_length=240)
    channel: Literal["email"] = "email"
    intent: Literal["feedback", "support", "privacy", "safety", "partnership"] = "feedback"
    message: str = Field(min_length=10, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppEventCreate(BaseModel):
    session_id: str | None = Field(default=None, max_length=120)
    event_name: AppEventName
    page: str | None = Field(default=None, max_length=80)
    target_type: str | None = Field(default=None, max_length=80)
    target_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_created_at: str | None = Field(default=None, max_length=80)


class AppEventsBatchCreate(BaseModel):
    events: list[AppEventCreate] = Field(min_length=1, max_length=25)


class FeedbackSubmissionCreate(BaseModel):
    category: FeedbackCategory = "feedback"
    message: str = Field(min_length=10, max_length=4000)
    allow_contact: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommunityInviteRequestCreate(BaseModel):
    channel: CommunityChannel
    message: str | None = Field(default=None, max_length=500)
    allow_contact: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentConversation(BaseModel):
    id: str
    status: Literal["active", "extracted"] = "active"
    agent_provider: str | None = None
    agent_model: str | None = None
    agent_mode: AgentMode = "know_me"
    agent_tone: AgentTone = "auto"
    agent_name: str | None = Field(default=None, max_length=40)
    agent_style_source_id: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


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
    message: str = Field(min_length=1, max_length=4000)


class AgentMessageFeedbackCreate(BaseModel):
    rating: AgentMessageFeedbackRating
    reason: str | None = Field(default=None, max_length=80)
    reasons: list[str] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(default=None, max_length=1000)


class DataPointFeedbackCreate(BaseModel):
    rating: DataPointFeedbackRating
    reason: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=1000)


class ProfileFactPatch(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=240)
    status: Literal["active", "rejected"] = "active"
    comment: str | None = Field(default=None, max_length=1000)
    confirmed: bool = False
    used_for_matching: bool | None = None
    used_for_chat_context: bool | None = None


class DataRequestCreate(BaseModel):
    request_type: DataRequestType
    message: str = Field(min_length=10, max_length=2000)


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
    content: str = Field(min_length=50, max_length=200000)


class DatingBasics(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    age: int | None = Field(default=None, ge=18, le=100)
    gender: Gender
    interested_in: InterestedIn
    city: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)


class UserProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    age: int | None = Field(default=None, ge=18, le=100)
    gender: Gender
    interested_in: InterestedIn
    city: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
