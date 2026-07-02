from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.prompt_engine.modules.identity import agent_persona_for_interest


@dataclass(frozen=True)
class CompanionBehavior:
    persona_name: str
    persona_presentation: str
    tone: str = "auto"
    max_reply_words: int = 35
    allow_light_playful: bool = True
    allow_romantic_roleplay: bool = False
    ask_question_policy: str = "at_most_one_soft_question"
    dating_focus: str = "gradual_understanding_for_matching"
    safety_level: str = "high_trust_no_impersonation"
    version: str = "v1"
    version_name: str = "v1_companion_basic"
    data_point_targets: tuple[str, ...] = ()


def build_companion_behavior(
    user_profile: dict[str, Any] | None,
    *,
    agent_name: str | None = None,
    tone: str = "auto",
    prompt_version: PromptBehaviorVersion | None = None,
) -> CompanionBehavior:
    persona = agent_persona_for_interest(str((user_profile or {}).get("interested_in") or ""))
    if agent_name and agent_name.strip():
        persona = {**persona, "name": agent_name.strip()}
    return CompanionBehavior(
        persona_name=persona["name"],
        persona_presentation=persona["presentation"],
        tone=tone,
        max_reply_words=int(os.getenv("AGENT_CHAT_REPLY_WORD_LIMIT", "35")),
        allow_light_playful=_allow_light_playful(prompt_version),
        allow_romantic_roleplay=False,
        version=prompt_version.version_id if prompt_version else "v1",
        version_name=prompt_version.name if prompt_version else "v1_companion_basic",
        data_point_targets=prompt_version.data_point_targets if prompt_version else (),
    )


def behavior_module_prompt(
    behavior: CompanionBehavior,
    user_profile: dict[str, Any] | None,
) -> str:
    gender = (user_profile or {}).get("gender") or "unknown"
    interested_in = (user_profile or {}).get("interested_in") or "unknown"
    display_name = (user_profile or {}).get("display_name") or "unknown"
    email = (user_profile or {}).get("email") or "unknown"
    location = (user_profile or {}).get("location") or "India"
    country = (user_profile or {}).get("country") or "India"
    timezone = (user_profile or {}).get("timezone") or "Asia/Kolkata"
    current_date = (user_profile or {}).get("current_date") or "unknown"
    current_time = (user_profile or {}).get("current_time") or "unknown"
    current_weekday = (user_profile or {}).get("current_weekday") or "unknown"
    playful_rule = (
        "Light playfulness is allowed when natural."
        if behavior.allow_light_playful
        else "Avoid playful teasing; stay warm and plain."
    )
    roleplay_rule = (
        "Romantic roleplay is allowed only if explicitly configured."
        if behavior.allow_romantic_roleplay
        else "Do not romantic-roleplay, claim intimacy, or pretend to be a real partner."
    )
    return (
        f"Prompt behavior version: {behavior.version} ({behavior.version_name}).\n"
        f"User identity: display_name={display_name}, email={email}.\n"
        f"User basics: gender={gender}, interested_in={interested_in}, "
        f"location={location}, country={country}.\n"
        f"Current context: date={current_date}, time={current_time}, "
        f"weekday={current_weekday}, timezone={timezone}.\n"
        f"Agent persona: name={behavior.persona_name}, "
        f"presentation={behavior.persona_presentation}.\n"
        f"Reply budget: usually <= {behavior.max_reply_words} words.\n"
        f"Question policy: {behavior.ask_question_policy}.\n"
        f"Dating focus: {behavior.dating_focus}.\n"
        f"Safety level: {behavior.safety_level}.\n"
        f"{playful_rule} {roleplay_rule}\n"
        "Use identity/location/time only when naturally helpful. Do not mention the user's email "
        "unless they ask about account details. If location is only a default, treat it as uncertain. "
        "Speak from this persona in a casual WhatsApp-like way, like a single ongoing personal chat. "
        "Use small replies, not big paragraphs. "
        "Do not keep saying your name. Do not turn every reply into a dating interview. "
        "Do not repeat the same supportive line again and again."
    )


def companion_intent_prompt() -> str:
    return (
        "Current internal behavior: Companion. This is the user's main personal chat with you. "
        "Talk like a warm girl/boy companion on WhatsApp: brief, natural, sometimes playful. "
        "Quietly learn the user's personality, values, lifestyle, emotional patterns, "
        "communication style, and relationship goals over time. Let the conversation breathe; "
        "do not force a profile question every turn."
    )


def _allow_light_playful(prompt_version: PromptBehaviorVersion | None) -> bool:
    env_value = os.getenv("AGENT_ALLOW_LIGHT_PLAYFUL")
    if env_value is not None:
        return env_value.lower() == "true"
    if not prompt_version:
        return True
    return bool(prompt_version.reply_style.get("allow_light_playful", True))
