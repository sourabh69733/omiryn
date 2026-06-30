from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Source = Literal["user_stated", "inferred", "unknown"]


class SourcedStringModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str = "unknown"
    source: Source = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: Any) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, str):
            normalized = value.strip()
            return normalized if normalized else "unknown"
        return str(value).strip() or "unknown"


class SourcedListModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    values: list[str] = Field(default_factory=list)
    source: Source = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, list):
            return []

        normalized = []
        seen = set()
        for item in value:
            if item is None:
                continue
            text = str(item).strip().lower().replace(" ", "_")
            if text and text not in seen:
                normalized.append(text)
                seen.add(text)
        return normalized


class ExtractedDatingProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_provider: str = "omiryn_agent"
    display_name: str | None = None
    age: int | None = Field(default=None, ge=18, le=100)
    city: SourcedStringModel = Field(default_factory=SourcedStringModel)
    relationship_intent: SourcedStringModel = Field(default_factory=SourcedStringModel)
    values: SourcedListModel = Field(default_factory=SourcedListModel)
    lifestyle: SourcedListModel = Field(default_factory=SourcedListModel)
    communication_style: SourcedStringModel = Field(default_factory=SourcedStringModel)
    family_expectations: SourcedStringModel = Field(default_factory=SourcedStringModel)
    children_preference: SourcedStringModel = Field(default_factory=SourcedStringModel)
    dealbreakers: SourcedListModel = Field(default_factory=SourcedListModel)
    soft_preferences: SourcedListModel = Field(default_factory=SourcedListModel)
    summary: str = ""
    extraction_warnings: list[str] = Field(default_factory=list)

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()


def normalize_extracted_profile(raw_profile: dict[str, Any], provider: str) -> dict[str, Any]:
    raw_profile = dict(raw_profile)
    raw_profile.setdefault("agent_provider", provider)
    profile = ExtractedDatingProfile.model_validate(raw_profile)
    warnings = extraction_warnings(profile)
    profile.extraction_warnings.extend(warnings)
    return profile.model_dump(mode="json")


def extraction_warnings(profile: ExtractedDatingProfile) -> list[str]:
    warnings = []
    required_fields = {
        "relationship_intent": profile.relationship_intent,
        "city": profile.city,
        "communication_style": profile.communication_style,
    }

    for field_name, sourced_value in required_fields.items():
        if sourced_value.value == "unknown":
            warnings.append(f"{field_name} is unknown")
        elif sourced_value.confidence < 0.5:
            warnings.append(f"{field_name} confidence is low")

    if not profile.values.values:
        warnings.append("values are missing")
    if not profile.dealbreakers.values:
        warnings.append("dealbreakers are missing")

    return warnings
