from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from omiryn.agent.providers import AgentProviderError, extract_profile, generate_agent_reply
from omiryn.matching import AgePreference, Dealbreaker, MatchProfile, score_match

STATIC_DIR = Path(__file__).parent / "static"
DRAFTS: dict[str, "DraftProfile"] = {}
CONVERSATIONS: dict[str, "AgentConversation"] = {}

app = FastAPI(
    title="Omiryn API",
    version="0.1.0",
    description="AI-assisted matchmaking platform API.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


class DraftProfile(BaseModel):
    id: str
    status: Literal["draft", "approved", "deleted"]
    submission: AgentProfileSubmission


class DraftPatch(BaseModel):
    display_name: str | None = None
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
    messages: list[dict[str, str]] = Field(default_factory=list)


class UserMessage(BaseModel):
    message: str = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/agent/conversations", status_code=201)
def create_agent_conversation() -> AgentConversation:
    conversation_id = str(uuid4())
    conversation = AgentConversation(
        id=conversation_id,
        messages=[
            {
                "role": "assistant",
                "content": (
                    "Hi, I am Omiryn's matchmaker. I will help create your private "
                    "relationship profile. Are you looking for long-term dating, "
                    "marriage, exploring, or something else?"
                ),
            }
        ],
    )
    CONVERSATIONS[conversation_id] = conversation
    return conversation


@app.get("/api/agent/conversations/{conversation_id}")
def get_agent_conversation(conversation_id: str) -> AgentConversation:
    return _get_existing_conversation(conversation_id)


@app.post("/api/agent/conversations/{conversation_id}/messages")
async def send_agent_message(conversation_id: str, payload: UserMessage) -> AgentConversation:
    conversation = _get_existing_conversation(conversation_id)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="Conversation already extracted.")

    conversation.messages.append({"role": "user", "content": payload.message})
    try:
        reply = await generate_agent_reply(conversation.messages)
    except (AgentProviderError, Exception) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    conversation.messages.append({"role": "assistant", "content": reply})
    CONVERSATIONS[conversation_id] = conversation
    return conversation


@app.post("/api/agent/conversations/{conversation_id}/extract")
async def extract_agent_conversation(conversation_id: str) -> dict[str, str]:
    conversation = _get_existing_conversation(conversation_id)
    try:
        raw_profile = await extract_profile(conversation.messages)
        submission = AgentProfileSubmission(
            agent_provider=raw_profile.get("agent_provider", "omiryn_agent"),
            display_name=raw_profile.get("display_name"),
            age=raw_profile.get("age"),
            city=raw_profile.get("city", {"value": "unknown"}),
            relationship_intent=raw_profile.get("relationship_intent", {"value": "unknown"}),
            values=raw_profile.get("values", {}),
            lifestyle=raw_profile.get("lifestyle", {}),
            communication_style=raw_profile.get(
                "communication_style", {"value": "unknown"}
            ),
            family_expectations=raw_profile.get(
                "family_expectations", {"value": "unknown"}
            ),
            children_preference=raw_profile.get(
                "children_preference", {"value": "unknown"}
            ),
            dealbreakers=raw_profile.get("dealbreakers", {}),
            soft_preferences=raw_profile.get("soft_preferences", {}),
            summary=raw_profile.get("summary", ""),
        )
    except (AgentProviderError, ValueError, TypeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    draft_id = str(uuid4())
    DRAFTS[draft_id] = DraftProfile(id=draft_id, status="draft", submission=submission)
    conversation.status = "extracted"
    CONVERSATIONS[conversation_id] = conversation
    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }


@app.post("/api/agent-submissions/profile", status_code=201)
def submit_agent_profile(submission: AgentProfileSubmission) -> dict[str, str]:
    draft_id = str(uuid4())
    DRAFTS[draft_id] = DraftProfile(id=draft_id, status="draft", submission=submission)

    return {
        "draft_id": draft_id,
        "status": "draft",
        "review_url": f"/drafts/{draft_id}",
    }


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: str) -> DraftProfile:
    return _get_existing_draft(draft_id)


@app.patch("/api/drafts/{draft_id}")
def update_draft(draft_id: str, patch: DraftPatch) -> DraftProfile:
    draft = _get_existing_draft(draft_id)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft profiles can be edited.")

    data = draft.submission.model_copy(deep=True)

    if patch.display_name is not None:
        data.display_name = patch.display_name
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
    DRAFTS[draft_id] = updated
    return updated


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: str) -> DraftProfile:
    draft = _get_existing_draft(draft_id)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft profiles can be approved.")

    approved = DraftProfile(id=draft.id, status="approved", submission=draft.submission)
    DRAFTS[draft_id] = approved
    return approved


@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: str) -> dict[str, str]:
    draft = _get_existing_draft(draft_id)
    DRAFTS[draft_id] = DraftProfile(id=draft.id, status="deleted", submission=draft.submission)
    return {"draft_id": draft_id, "status": "deleted"}


@app.get("/drafts/{draft_id}")
def draft_review_page(draft_id: str) -> FileResponse:
    _get_existing_draft(draft_id)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/demo/matches")
def demo_matches() -> dict[str, object]:
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


def _get_existing_draft(draft_id: str) -> DraftProfile:
    draft = DRAFTS.get(draft_id)
    if not draft or draft.status == "deleted":
        raise HTTPException(status_code=404, detail="Draft profile not found.")
    return draft


def _get_existing_conversation(conversation_id: str) -> AgentConversation:
    conversation = CONVERSATIONS.get(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Agent conversation not found.")
    return conversation
