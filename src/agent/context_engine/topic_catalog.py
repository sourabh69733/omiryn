from __future__ import annotations

from dataclasses import dataclass

from agent.context_engine.models import ContextQueryIntent
from agent.context_engine.utils import memory_terms, normalized_memory_text


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
        trigger_terms=("whatsapp", "abhishek", "message", "tone", "style", "chat"),
        freshness_window=8,
    ),
    TopicDefinition(
        id="future_partner_attention",
        bucket="romantic",
        label="Playful partner attention: consistency, effort, texting, possessiveness, care.",
        data_targets=("affection_style", "partner_expectations", "communication_style"),
        trigger_terms=("partner", "crush", "attention", "love", "relationship"),
    ),
    TopicDefinition(
        id="future_partner_intent",
        bucket="future_partner",
        label="Future relationship direction: exploring, serious, long-term, marriage, family fit.",
        data_targets=("relationship_intent", "family_expectations", "dealbreakers"),
        trigger_terms=("marriage", "serious", "long", "future", "family"),
    ),
    TopicDefinition(
        id="emotional_side",
        bucket="emotional_depth",
        label="Emotional side: loneliness, trust, attachment, comfort, what makes the user feel safe.",
        data_targets=("attachment_style", "values", "emotional_needs"),
        trigger_terms=("feel", "trust", "alone", "hurt", "emotional"),
    ),
    TopicDefinition(
        id="personal_stories",
        bucket="personal_story",
        label="Personal stories: childhood, school, first crush, embarrassing/funny memory.",
        data_targets=("personality", "attraction_preferences", "social_lifestyle"),
        trigger_terms=("school", "childhood", "story", "memory", "crush"),
    ),
    TopicDefinition(
        id="social_life",
        bucket="social_life",
        label="Social life: friends, weekends, parties, close circle, introvert/extrovert pattern.",
        data_targets=("lifestyle", "social_lifestyle", "values"),
        trigger_terms=("friends", "weekend", "party", "social", "circle"),
    ),
    TopicDefinition(
        id="conflict_style",
        bucket="conflict_style",
        label="Conflict style: anger, silent treatment, repair, expectations during fights.",
        data_targets=("conflict_style", "communication_style", "dealbreakers"),
        trigger_terms=("fight", "anger", "ignore", "argument", "sorry"),
    ),
    TopicDefinition(
        id="safe_intimacy",
        bucket="intimate_safe",
        label="Safe intimacy: chemistry, affection, comfort, boundaries, romantic closeness.",
        data_targets=("affection_style", "boundaries", "attraction_preferences"),
        trigger_terms=("intimate", "romantic", "sexy", "hot", "chemistry", "touch"),
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
    if "adult_flirty" in labels and topic.bucket == "intimate_safe":
        score += 6
    if "story_or_long_reply" in labels and topic.bucket == "personal_story":
        score += 4
    if "low_information" in labels and topic.bucket in {"romantic", "personal_story", "intimate_safe"}:
        score += 2
    return score


def _default_topic_rotation(labels: set[str]) -> tuple[TopicDefinition, ...]:
    if "low_information" in labels:
        preferred = {"future_partner_attention", "personal_stories", "safe_intimacy"}
    else:
        preferred = {"future_partner_attention", "emotional_side", "social_life"}
    return tuple(topic for topic in TOPIC_CATALOG if topic.id in preferred)
