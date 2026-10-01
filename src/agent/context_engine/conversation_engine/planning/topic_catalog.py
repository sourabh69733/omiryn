"""Defines conversation topics and ranks them against the current user intent."""

from __future__ import annotations

from dataclasses import dataclass

from agent.context_engine.contracts.models import ContextQueryIntent
from agent.context_engine.shared.text import memory_terms, normalized_memory_text

COMMON_STARTER_TOPIC_POLICY = (
    "Do not start generic music, movie, truth-or-dare, or how-was-your-day topics.",
    "Use common topics only when the user explicitly brings them up, or when tied to a sharper personal angle.",
)


@dataclass(frozen=True)
class TopicDefinition:
    id: str
    bucket: str
    label: str
    data_targets: tuple[str, ...]
    trigger_terms: tuple[str, ...] = ()
    freshness_window: int = 18


TOPIC_CATALOG: tuple[TopicDefinition, ...] = (
    TopicDefinition(
        id="whatsapp_person_analysis",
        bucket="whatsapp_context",
        label="Talk about a person, tone, topics, or messages from uploaded WhatsApp context.",
        data_targets=("communication_style", "tone_preference"),
        trigger_terms=("whatsapp", "message", "tone", "style", "chat"),
        freshness_window=8,
    ),
    TopicDefinition(
        id="friendship",
        bucket="friendship",
        label="Friendship: who they click with, a friend who mattered, what they want from new friends.",
        data_targets=("friend_wish", "social_energy", "keeping_in_touch"),
        trigger_terms=("friend", "friends", "friendship", "dost", "yaar", "lonely"),
    ),
    TopicDefinition(
        id="humor_and_takes",
        bucket="humor",
        label="Humor and honest takes: what makes them laugh, an opinion they would defend.",
        data_targets=("humor", "values"),
        trigger_terms=("funny", "joke", "meme", "laugh", "opinion"),
    ),
    TopicDefinition(
        id="everyday_life",
        bucket="everyday_life",
        label="Their days: study or work, routine, something they could talk about for hours.",
        data_targets=("daily_life", "interests"),
        trigger_terms=("college", "class", "exam", "work", "office", "hobby"),
    ),
    TopicDefinition(
        id="emotional_side",
        bucket="emotional_depth",
        label="Emotional side: loneliness, trust, comfort, what makes the user feel safe.",
        data_targets=("values", "conflict", "friend_wish"),
        trigger_terms=("feel", "trust", "alone", "hurt", "emotional"),
    ),
    TopicDefinition(
        id="personal_stories",
        bucket="personal_story",
        label="Personal stories: childhood, school, an embarrassing or funny memory.",
        data_targets=("stories", "humor"),
        trigger_terms=("school", "childhood", "memory"),
    ),
    TopicDefinition(
        id="social_life",
        bucket="social_life",
        label="Social life: weekends, parties, close circle, quiet or loud, planned or spontaneous.",
        data_targets=("social_energy", "interests"),
        trigger_terms=("weekend", "party", "social", "circle", "plans"),
    ),
    TopicDefinition(
        id="conflict_style",
        bucket="conflict_style",
        label="Conflict: anger, silent treatment, making up, what they will not tolerate.",
        data_targets=("conflict", "deal_breakers", "accepts"),
        trigger_terms=("fight", "anger", "ignore", "argument", "sorry"),
    ),
    TopicDefinition(
        # Fine to talk about when the user raises it; never steered to, never flirting.
        id="relationships",
        bucket="relationships",
        label="Relationships, crushes or marriage the user brings up: listen and give an honest take.",
        data_targets=("values", "stories"),
        trigger_terms=("crush", "relationship", "marriage", "partner", "breakup"),
    ),
)


def relevant_topics_for_intent(
    user_text: str,
    intent: ContextQueryIntent,
    *,
    limit: int = 4,
) -> list[TopicDefinition]:
    labels = set(intent.labels)
    terms = memory_terms(user_text)
    normalized = normalized_memory_text(user_text)
    scored: list[tuple[int, TopicDefinition]] = []
    for topic in TOPIC_CATALOG:
        score = _topic_score(topic, labels, terms, normalized)
        if score > 0:
            scored.append((score, topic))
    if not scored:
        scored = [(1, topic) for topic in _default_topic_rotation(labels)]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [topic for _, topic in scored[:limit]]


def topic_by_id(topic_id: str) -> TopicDefinition | None:
    return next((topic for topic in TOPIC_CATALOG if topic.id == topic_id), None)


def _topic_score(
    topic: TopicDefinition,
    labels: set[str],
    terms: set[str],
    normalized: str,
) -> int:
    score = sum(2 for term in topic.trigger_terms if term in terms or term in normalized)
    if "whatsapp" in labels and topic.bucket == "whatsapp_context":
        score += 8
    if "style" in labels and topic.id == "whatsapp_person_analysis":
        score += 5
    if (
        {"low_information", "boredom_complaint"} & labels
        and topic.bucket in {"humor", "personal_story", "friendship"}
    ):
        score += 2
    return score


def _default_topic_rotation(labels: set[str]) -> tuple[TopicDefinition, ...]:
    if {"low_information", "boredom_complaint"} & labels:
        preferred = {"humor_and_takes", "personal_stories", "friendship"}
    else:
        preferred = {"friendship", "everyday_life", "social_life"}
    return tuple(topic for topic in TOPIC_CATALOG if topic.id in preferred)
