"""Selects stored memory and attached sources for current-turn context."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from agent.config import agent_pipeline_config
from agent.context_engine.contracts.models import AgentContext, ContextQueryIntent, ThreadGuidance
from agent.context_engine.conversation_engine.personalization import style_adaptation_guide
from agent.context_engine.conversation_engine.state import (
    conversation_thread_context_sources,
    conversation_thread_guidance,
)
from agent.context_engine.conversation_engine.understanding.rules.intent import (
    RECENCY_QUERY_TERMS,
    context_query_intent,
)
from agent.context_engine.shared.text import memory_terms, normalized_memory_text, source_identity
from agent.memory_engine.data_points import rank_data_points_for_context
from agent.memory_engine.memories import (
    BROAD_RECALL_MEMORY_LIMIT,
    retrieve_agent_memories_for_reply,
)
from agent.memory_engine.memories.retrieval import might_fit_memories
from agent.memory_engine.behavior.retrieval import retrieve_agent_behavior_rules_for_context
from agent.memory_engine.data_points.retrieval.profile_facts import (
    retrieve_profile_facts_for_context,
)
from agent.memory_engine.data_points.retrieval.whatsapp import (
    retrieve_whatsapp_imports,
    retrieve_whatsapp_memory,
)
from agent.memory_engine.processing.service import get_processing_state
from agent.memory_engine.memories.ranking import text_relevance
from agent.shared.clock import utc_now
from agent.shared.timeline import (
    current_session_start,
    clock_label,
    date_label,
    humanize_gap,
    local_label,
    parse_time,
    relative_day,
    session_gap,
    user_zone,
)
from storage import (
    get_conversation,
    get_user_card,
    list_active_self_notes,
    list_open_questions,
    mark_open_question_offered,
    get_user_timezone,
    list_agent_context_snapshots,
    list_agent_message_feedback,
    list_context_sources,
    list_user_context_sources,
)
from text_vectors import build_text_embedding, cosine_similarity

STYLE_CONTEXT_SOURCE_TYPES = {"whatsapp_chat", "friend_style"}
MEMORY_RETRIEVAL_LIMIT = 2
DATA_POINT_CONTEXT_LIMIT = 4
WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT = 2
WHATSAPP_FUEL_RETRIEVAL_LIMIT = 1
DATA_POINT_SOURCE_TYPE = "data_points"
AGENT_MEMORIES_V3_SOURCE_TYPE = "agent_memories_v3"
# Procedural memories (how the user wants to be talked to) get their own source, kept apart
# from facts so the reply prompt can place them where they are followed.
HOW_TO_TALK_SOURCE_TYPE = "how_to_talk"
CONVERSATION_SUMMARY_SOURCE_TYPE = "conversation_summary"
USER_CARD_SOURCE_TYPE = "user_card"
RECENT_SESSIONS_SOURCE_TYPE = "recent_sessions"
RECENT_SESSION_LIMIT = 5
SELF_NOTES_SOURCE_TYPE = "agent_self_notes"
OPEN_QUESTIONS_SOURCE_TYPE = "open_questions"
MIGHT_FIT_SOURCE_TYPE = "might_fit"
REPLY_FEEDBACK_SOURCE_TYPE = "reply_feedback"
# Recent ratings shown on every reply, newest first; older ones have done their job.
REPLY_FEEDBACK_WINDOW_DAYS = 30
REPLY_FEEDBACK_DISLIKED = 3
REPLY_FEEDBACK_LIKED = 2
_FEEDBACK_REASON_WORDS = {
    "too_much": "too much",
    "bad_tone": "the tone felt off",
    "not_me": "not like them",
    "wrong_memory": "got something about them wrong",
    "not_helpful": "not helpful",
    "unsafe": "felt unsafe",
}
# A memory offered as "might fit" waits this many replies before it is offered again.
MIGHT_FIT_ROTATION_REPLIES = 5
# Replies in one session that may see the same open question; then it waits for the next session,
# so an unanswered doubt never turns into nagging.
OPEN_QUESTION_REPLIES_PER_SESSION = 3
# Open promises always show; opinions, tastes and jokes only when the message touches them.
SELF_NOTE_PROMISE_LIMIT = 4
SELF_NOTE_TOPIC_LIMIT = 5
_SELF_NOTE_RELEVANCE_FLOOR = 0.12
AGENT_BEHAVIOR_RULES_SOURCE_TYPE = "agent_behavior_rules"
WHATSAPP_STRUCTURED_SOURCE_TYPE = "whatsapp_structured_context"
MEMORY_TRIGGER_TERMS = {
    "chat",
    "context",
    "message",
    "messages",
    "memory",
    "remember",
    "saved",
    "style",
    "talk",
    "talking",
    "topics",
    "topic",
    "tone",
    "imported",
    "upload",
    "uploaded",
    "way",
    "whatsapp",
    "chatgpt",
    "claude",
    "gemini",
    "summary",
    "profile",
    "convo",
    "msg",
    "about me",
    "know about me",
    "what do you know",
    "last topic",
    "last message",
    "past chat",
    "conversation",
}
MEMORY_TRIGGER_PHRASES = {
    "kaise baat",
    "kaise text",
    "kaise bol",
    "kis style",
    "kya baat",
    "kya baate",
    "hum kya",
    "last convo",
    "pichli baat",
    "pehle kya",
    "previous chat",
    "uploaded chat",
    "where did",
    "whatsapp chat",
}


def build_reply_context(
    conversation_id: str,
    user_text: str,
    *,
    user_id: str | None = None,
    user_profile: dict[str, Any] | None = None,
    style_source_id: str | None = None,
    strict_intent: bool = False,
    memory_query_embedding: dict[str, Any] | None = None,
) -> AgentContext:
    thread_guidance = conversation_thread_guidance(
        conversation_id,
        user_id,
        user_text,
    )
    return AgentContext(
        user_profile=user_profile,
        context_sources=build_reply_context_sources(
            conversation_id,
            style_source_id,
            user_text,
            user_id,
            strict_intent=strict_intent,
            thread_guidance=thread_guidance,
            memory_query_embedding=memory_query_embedding,
        ),
        thread_guidance=thread_guidance,
    )


def build_reply_context_sources(
    conversation_id: str,
    style_source_id: str | None,
    user_text: str,
    user_id: str | None = None,
    *,
    strict_intent: bool = False,
    thread_guidance: ThreadGuidance | None = None,
    memory_query_embedding: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pipeline = agent_pipeline_config()
    query_intent = context_query_intent(user_text, strict_whatsapp=strict_intent)
    all_sources = list_context_sources(conversation_id, user_id)
    attached_sources = _valid_attached_context_sources(all_sources, user_id)
    selected_styles = _selected_style_sources(all_sources, style_source_id)
    retrieved_sources = _relevant_memory_sources(attached_sources, user_text)
    agent_behavior_sources = (
        []
        if pipeline.memory_contract_version == 3
        else _agent_behavior_rule_context_sources(user_id)
    )
    if pipeline.memory_contract_version == 3:
        durable_memory_sources = _agent_memory_v3_context_sources(
            user_id,
            user_text,
            memory_query_embedding,
            broad="profile_recall" in query_intent.labels,
        )
        durable_memory_sources += _might_fit_sources(conversation_id, user_id, durable_memory_sources)
    else:
        durable_memory_sources = _data_point_context_sources(user_id, user_text)
    structured_whatsapp_sources = _structured_whatsapp_context_sources(
        all_sources,
        attached_sources,
        selected_styles,
        user_text,
        user_id,
        query_intent,
    )
    continuity_sources = (
        _user_card_sources(user_id)
        + _recent_sessions_sources(conversation_id, user_id)
        + _conversation_summary_sources(conversation_id, user_id)
        + _self_note_sources(user_id, user_text)
        + _open_question_sources(conversation_id, user_id)
        + _reply_feedback_sources(user_id)
    ) + conversation_thread_context_sources(
        conversation_id,
        user_id,
        user_text,
        guidance=thread_guidance,
    )

    if selected_styles:
        selected_style_ids = {_source_identity(source) for source in selected_styles}
        memory_sources = continuity_sources + _ordered_memory_context_sources(
            agent_behavior_sources,
            durable_memory_sources,
            structured_whatsapp_sources,
            query_intent,
        )
        return (
            selected_styles
            + memory_sources
            + [
                source
                for source in retrieved_sources
                if _source_identity(source) not in selected_style_ids
            ]
        )

    return continuity_sources + (
        _ordered_memory_context_sources(
            agent_behavior_sources,
            durable_memory_sources,
            structured_whatsapp_sources,
            query_intent,
        )
        + retrieved_sources
    )


def build_profile_extraction_context_sources(
    conversation_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        source
        for source in _valid_attached_context_sources(
            list_context_sources(conversation_id, user_id),
            user_id,
        )
        if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
    ]


def selected_style_source_exists(
    conversation_id: str,
    style_source_id: str | None,
    user_id: str | None = None,
) -> bool:
    if not style_source_id:
        return True
    return any(
        _source_matches_id(source, style_source_id)
        and source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
        for source in list_context_sources(conversation_id, user_id)
    )


def _valid_attached_context_sources(
    sources: list[dict[str, Any]],
    user_id: str | None,
) -> list[dict[str, Any]]:
    reusable_source_ids = {
        str(source["id"])
        for source in list_user_context_sources(user_id)
        if not (
            isinstance(source.get("metadata"), dict)
            and source["metadata"].get("original_source_id")
        )
    }
    return [
        source
        for source in sources
        if isinstance(source.get("metadata"), dict)
        and source["metadata"].get("original_source_id")
        and str(source["metadata"].get("original_source_id")) in reusable_source_ids
    ]


def _selected_style_sources(
    sources: list[dict[str, Any]],
    style_source_id: str | None,
) -> list[dict[str, Any]]:
    style_sources = [
        source for source in sources if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    ]
    if not style_source_id:
        return []
    selected = [source for source in style_sources if _source_matches_id(source, style_source_id)]
    return selected


def _source_matches_id(source: dict[str, Any], source_id: str | None) -> bool:
    if not source_id:
        return False
    return _source_identity(source) == source_id or source.get("id") == source_id


def _source_identity(source: dict[str, Any]) -> str:
    return source_identity(source)


def _data_point_context_sources(user_id: str | None, user_text: str) -> list[dict[str, Any]]:
    if not user_id or not _should_retrieve_memory(user_text):
        return []
    ranked_points = rank_data_points_for_context(
        retrieve_profile_facts_for_context(user_id),
        user_text,
        limit=DATA_POINT_CONTEXT_LIMIT,
    )
    if not ranked_points:
        return []
    lines = [
        "User data points relevant to this message.",
        "Use these as compact stored memory. Do not mention internal labels unless useful.",
    ]
    for point in ranked_points:
        value = point.get("value") or {}
        lines.append(
            "- "
            f"{point.get('label')}; "
            f"category={point.get('category')}; "
            f"value={_data_point_value_preview(value)}"
        )
    return [
        {
            "source_type": DATA_POINT_SOURCE_TYPE,
            "title": "Relevant data points",
            "content": "\n".join(lines),
            "metadata": {
                "point_count": len(ranked_points),
                "point_ids": [point.get("id") for point in ranked_points],
            },
        }
    ]


def _user_card_sources(user_id: str | None) -> list[dict[str, Any]]:
    """The short note on who the user is, kept across all chats by background cognition."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    card = get_user_card(user_id) or ""
    own_words = _self_description(user_id)
    if not card and not own_words:
        return []
    content = (
        "What you know about the user from all your chats. Use it naturally; do not "
        "recite it or say you keep notes.\n" + card
    ).rstrip()
    if own_words:
        # Written by the user on their profile: their own view of themselves, which wins over guesses.
        content += "\nHow they describe themselves on their profile: " + own_words
    return [
        {
            "source_type": USER_CARD_SOURCE_TYPE,
            "title": "About the user",
            "content": content,
            "metadata": {"card_chars": len(card), "self_description": bool(own_words)},
        }
    ]


def _self_description(user_id: str) -> str:
    """The intro and tags the user edited on their profile, or "" when Omi wrote them."""
    from storage.vibe_cards import get_vibe_card

    intro = get_vibe_card(user_id).get("intro") or {}
    if not intro.get("edited") or not intro.get("text"):
        return ""
    chips = ", ".join(str(chip) for chip in intro.get("chips") or [])
    return str(intro["text"]) + (f" (tags: {chips})" if chips else "")


def _recent_sessions_sources(conversation_id: str, user_id: str | None) -> list[dict[str, Any]]:
    """The last few chat sessions, one dated line each, from the background session log."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    state = get_processing_state(conversation_id, user_id)
    entries = state.handoff.session_log[-RECENT_SESSION_LIMIT:] if state else ()
    if not entries:
        return []
    now = utc_now()
    zone = user_zone(get_user_timezone(user_id))
    lines = ["Your recent chat sessions with the user, oldest first (start to end time):"]
    for entry in entries:
        started, ended = parse_time(entry.started_at), parse_time(entry.ended_at)
        if started is None:
            continue
        current = ended is not None and now - ended < session_gap()
        span = _session_span(started, ended, zone)
        when = "this session so far" if current else f"ended {humanize_gap(now - (ended or started))} ago"
        line = f"- {span} ({when}): {entry.gist}"
        if entry.unfinished:
            line += f" Left open: {entry.unfinished}"
        lines.append(line)
    return [
        {
            "source_type": RECENT_SESSIONS_SOURCE_TYPE,
            "title": "Recent sessions",
            "content": "\n".join(lines),
            "metadata": {"session_count": len(lines) - 1},
        }
    ]


def _session_span(started: datetime, ended: datetime | None, zone: Any) -> str:
    """'Saturday 26 Sep, 5:11 pm to 10:18 pm': a session is a stretch of time, not a moment."""
    start = started.astimezone(zone)
    if ended is None or ended <= started:
        return local_label(start)
    end = ended.astimezone(zone)
    end_text = clock_label(end) if end.date() == start.date() else local_label(end)
    return f"{local_label(start)} to {end_text}"


def _might_fit_sources(
    conversation_id: str,
    user_id: str | None,
    memory_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Things Omi knows that the message does not touch but the moment might suit."""
    if not user_id:
        return []
    shown = {
        str(memory_id)
        for source in memory_sources
        for memory_id in (source.get("metadata") or {}).get("memory_ids") or []
    }
    memories = might_fit_memories(
        user_id,
        exclude_ids=shown,
        recently_offered=_recently_offered(conversation_id, user_id),
    )
    if not memories:
        return []
    zone = user_zone(get_user_timezone(user_id))
    lines = [
        "Things you know about them that this message does not touch. Use at most one, only if it "
        "fits the moment naturally (a quiet or open turn); their message comes first. Never list them.",
        *(f"- {memory_sentence(memory)}{_memory_time_note(memory, zone)}" for memory in memories),
    ]
    return [
        {
            "source_type": MIGHT_FIT_SOURCE_TYPE,
            "title": "Might fit",
            "content": "\n".join(lines),
            "metadata": {"memory_ids": [memory.get("id") for memory in memories]},
        }
    ]


def _recently_offered(conversation_id: str, user_id: str) -> set[str]:
    offered: set[str] = set()
    for snapshot in list_agent_context_snapshots(
        conversation_id, user_id, limit=MIGHT_FIT_ROTATION_REPLIES
    ):
        for source in (snapshot.get("context") or {}).get("sources") or []:
            if source.get("source_type") == MIGHT_FIT_SOURCE_TYPE:
                offered.update(str(item) for item in (source.get("metadata") or {}).get("memory_ids") or [])
    return offered


def _reply_feedback_sources(user_id: str | None) -> list[dict[str, Any]]:
    """Replies the user rated, so the next reply learns from them right away."""
    if not user_id:
        return []
    cutoff = utc_now() - timedelta(days=REPLY_FEEDBACK_WINDOW_DAYS)
    disliked: list[str] = []
    liked: list[str] = []
    chats: dict[str, list[dict[str, Any]]] = {}
    for item in list_agent_message_feedback(user_id=user_id):  # newest first
        created = parse_time(item.get("created_at"))
        if created is not None and created < cutoff:
            break
        bucket = liked if item["rating"] == "good" else disliked
        if len(bucket) >= (REPLY_FEEDBACK_LIKED if bucket is liked else REPLY_FEEDBACK_DISLIKED):
            continue
        conversation_id = str(item["conversation_id"])
        if conversation_id not in chats:
            chats[conversation_id] = list((get_conversation(conversation_id, user_id) or {}).get("messages") or [])
        messages = chats[conversation_id]
        index = int(item["message_index"])
        reply = str(messages[index].get("content") or "") if 0 <= index < len(messages) else ""
        if not reply.strip():
            continue
        reasons = [
            _FEEDBACK_REASON_WORDS[reason]
            for reason in (item.get("metadata") or {}).get("reasons") or []
            if reason in _FEEDBACK_REASON_WORDS
        ]
        note = "; ".join(filter(None, [", ".join(reasons), str(item.get("comment") or "").strip()[:160]]))
        quoted = " ".join(reply.replace("<next_message>", " ").split())[:160]
        bucket.append(f"- \"{quoted}\"" + (f" ({note})" if note and bucket is disliked else ""))
    if not disliked and not liked:
        return []
    lines = ["Replies of yours they rated. Learn the pattern; never repeat these lines or mention the ratings."]
    if disliked:
        lines += ["They disliked:", *disliked]
    if liked:
        lines += ["They liked:", *liked]
    return [
        {
            "source_type": REPLY_FEEDBACK_SOURCE_TYPE,
            "title": "Replies they rated",
            "content": "\n".join(lines),
            "metadata": {"disliked": len(disliked), "liked": len(liked)},
        }
    ]


def _open_question_sources(conversation_id: str, user_id: str | None) -> list[dict[str, Any]]:
    """The oldest thing background cognition was unsure about, for the companion to ask if it fits."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    questions = list_open_questions(user_id)
    if not questions:
        return []
    messages = list((get_conversation(conversation_id, user_id) or {}).get("messages") or [])
    session = f"{conversation_id}:{current_session_start(messages)}"
    question = next(
        (
            item
            for item in questions
            if item["offered_session"] != session
            or item["offered_count"] < OPEN_QUESTION_REPLIES_PER_SESSION
        ),
        None,
    )
    if question is None:
        return []
    mark_open_question_offered(user_id, question["id"], session)
    return [
        {
            "source_type": OPEN_QUESTIONS_SOURCE_TYPE,
            "title": "Something you are unsure about",
            "content": "\n".join(
                [
                    f"You are unsure: {question['text']}",
                    "Ask it in your own words only if it fits naturally right now. Skip it if they are "
                    "upset, busy with something else, or asked for no questions. If this chat already "
                    "answered it, do not ask again.",
                ]
            ),
            "metadata": {"open_question_id": question["id"]},
        }
    ]


def _self_note_sources(user_id: str | None, user_text: str) -> list[dict[str, Any]]:
    """What the companion said before: open promises, plus opinions this message touches."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    notes = list_active_self_notes(user_id)
    promises = [note for note in notes if note["kind"] == "promise"][:SELF_NOTE_PROMISE_LIMIT]
    scored = sorted(
        (
            (text_relevance(user_text, note["text"]), note)
            for note in notes
            if note["kind"] != "promise"
        ),
        key=lambda item: -item[0],
    )
    topical = [note for score, note in scored if score >= _SELF_NOTE_RELEVANCE_FLOOR]
    chosen = promises + topical[:SELF_NOTE_TOPIC_LIMIT]
    if not chosen:
        return []
    zone = user_zone(get_user_timezone(user_id))
    today = utc_now().astimezone(zone).date()
    lines = [
        "Things you said to this user before. Stay consistent with these opinions unless you "
        "have a reason to change your mind, and keep your promises.",
    ]
    for note in chosen:
        due = parse_time(note.get("due_at"))
        when = ""
        if due:
            local = due.astimezone(zone)
            when = f" (due {date_label(local)}, {relative_day(local.date(), today)})"
        lines.append(f"- {note['kind']}: {note['text']}{when}")
    return [
        {
            "source_type": SELF_NOTES_SOURCE_TYPE,
            "title": "Things you said before",
            "content": "\n".join(lines),
            "metadata": {"note_ids": [note["id"] for note in chosen]},
        }
    ]


def _conversation_summary_sources(
    conversation_id: str,
    user_id: str | None,
) -> list[dict[str, Any]]:
    """The background-written summary of this chat, for parts beyond the recent messages."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    state = get_processing_state(conversation_id, user_id)
    summary = state.handoff.conversation_summary if state else ""
    if not summary:
        return []
    return [
        {
            "source_type": CONVERSATION_SUMMARY_SOURCE_TYPE,
            "title": "Earlier in this chat",
            "content": (
                "Summary of older parts of this conversation. The recent messages are more "
                "exact; trust them when they differ.\n" + summary
            ),
            "metadata": {"processed_through_message_index": state.processed_through_message_index},
        }
    ]


def _agent_memory_v3_context_sources(
    user_id: str | None,
    user_text: str,
    query_embedding: dict[str, Any] | None = None,
    *,
    broad: bool = False,
) -> list[dict[str, Any]]:
    if not user_id:
        return []
    memories = retrieve_agent_memories_for_reply(
        user_id,
        user_text,
        query_embedding=query_embedding,
        broad=broad,
        **({"limit": BROAD_RECALL_MEMORY_LIMIT} if broad else {}),
    )
    if not memories:
        return []
    style = [memory for memory in memories if memory.get("kind") == "procedural"]
    facts = [memory for memory in memories if memory.get("kind") != "procedural"]
    return _how_to_talk_sources(style) + (_memory_facts_sources(user_id, facts) if facts else [])


def _how_to_talk_sources(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not memories:
        return []
    lines = ["How the user asked you to talk to them, in earlier chats. Follow it unless they change it."]
    lines.extend(f"- {memory_sentence(memory)}" for memory in memories)
    return [
        {
            "source_type": HOW_TO_TALK_SOURCE_TYPE,
            "title": "How to talk to the user",
            "content": "\n".join(lines),
            "metadata": {
                "memory_count": len(memories),
                "memory_ids": [memory.get("id") for memory in memories],
                "memory_kinds": [memory.get("kind") for memory in memories],
            },
        }
    ]


def _memory_facts_sources(user_id: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zone = user_zone(get_user_timezone(user_id))
    lines = [
        "Relevant durable memories about the user.",
        "Use only when helpful; do not quote them as a list or say you have stored notes.",
        "Memories about relationships describe lived history, not a desired partner trait.",
        "Dates carry their distance from today in brackets; use that wording (e.g. 'this Friday, "
        "in 2 days') rather than repeating the user's older relative words.",
        "Do not present past events as current. 'told you' is when the user said it.",
    ]
    for memory in memories:
        lines.append(f"- {memory_sentence(memory)}{_memory_time_note(memory, zone)}")
    return [
        {
            "source_type": AGENT_MEMORIES_V3_SOURCE_TYPE,
            "title": "Relevant durable memories",
            "content": "\n".join(lines),
            "metadata": {
                "memory_count": len(memories),
                "memory_ids": [memory.get("id") for memory in memories],
                "memory_kinds": [memory.get("kind") for memory in memories],
            },
        }
    ]


def memory_sentence(memory: dict[str, Any]) -> str:
    """The memory as plain text: its stored sentence, else a readable key and value."""
    statement = str(memory.get("statement") or "").strip()
    if statement:
        return statement
    key = _readable_key(memory.get("key"))
    value = _readable_value(memory.get("value"))
    return f"{key}: {value}" if key else value


def _readable_key(key: Any) -> str:
    text = " ".join(str(key or "").replace("_", " ").replace(".", " ").split())
    return text[:1].upper() + text[1:]


def _readable_value(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(
            f"{_readable_key(name).lower()}: {_readable_value(item)}"
            for name, item in value.items()
            if item not in (None, "", [], {})
        )
    if isinstance(value, list):
        return ", ".join(_readable_value(item) for item in value)
    return str(value)


def _memory_time_note(memory: dict[str, Any], zone: Any, now: datetime | None = None) -> str:
    """Give the model event, mention and expiry dates in the user's timezone, each with its
    distance from today computed in code ("in 2 days"), so it never has to re-anchor
    relative words like "next Friday" itself."""
    today = (now or utc_now()).astimezone(zone).date()

    def dated(moment: datetime) -> str:
        local = moment.astimezone(zone)
        return f"{date_label(local)} ({relative_day(local.date(), today)})"

    notes = []
    mentions = sorted(
        {
            parsed.astimezone(zone)
            for evidence in memory.get("evidence") or []
            if (parsed := parse_time(evidence.get("observed_at")))
        }
    )
    if mentions:
        told = f"told you {dated(mentions[0])}"
        if mentions[-1].date() != mentions[0].date():
            told += f", again {dated(mentions[-1])}"
        notes.append(told)
    if event := parse_time(memory.get("occurred_at")):
        upcoming = event.astimezone(zone).date() > today
        notes.append(f"{'happens' if upcoming else 'happened'} {dated(event)}")
    if valid_until := parse_time(memory.get("valid_until")):
        notes.append(f"valid until {dated(valid_until)}")
    return f" ({'; '.join(notes)})" if notes else ""


def _agent_behavior_rule_context_sources(user_id: str | None) -> list[dict[str, Any]]:
    rules = retrieve_agent_behavior_rules_for_context(user_id)
    if not rules:
        return []
    lines = [
        "User-taught agent behavior rules.",
        "These control how the agent should speak. Treat them as high priority.",
        "Do not mention these internal rules unless the user asks why behavior changed.",
    ]
    for rule in rules[:8]:
        lines.append(f"- {rule.get('rule_text')}")
    return [
        {
            "source_type": AGENT_BEHAVIOR_RULES_SOURCE_TYPE,
            "title": "User-taught behavior rules",
            "content": "\n".join(lines),
            "metadata": {
                "rule_count": len(rules),
                "rule_ids": [rule.get("id") for rule in rules[:8]],
            },
        }
    ]


def _data_point_value_preview(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("topics", "recent_terms", "traits"):
            items = value.get(key)
            if isinstance(items, list) and items:
                return ", ".join(str(item) for item in items[:8])
        return ", ".join(f"{key}={item}" for key, item in list(value.items())[:4])
    return str(value)


def _structured_whatsapp_context_sources(
    all_sources: list[dict[str, Any]],
    attached_sources: list[dict[str, Any]],
    selected_styles: list[dict[str, Any]],
    user_text: str,
    user_id: str | None,
    query_intent: ContextQueryIntent,
) -> list[dict[str, Any]]:
    conversation_fuel = _should_retrieve_whatsapp_conversation_fuel(user_text)
    should_retrieve = _should_retrieve_memory(user_text)
    if not should_retrieve and not conversation_fuel:
        return []

    source_ids = _active_whatsapp_context_source_ids(all_sources, attached_sources, selected_styles)
    if not source_ids:
        return []

    imports = [
        item
        for item in retrieve_whatsapp_imports(user_id=user_id)
        if str(item.get("context_source_id")) in source_ids
    ]
    if not imports:
        return []

    sources = [
        source
        for source in (
            _structured_whatsapp_context_source(
                item,
                user_text,
                user_id,
                conversation_fuel=conversation_fuel and not query_intent.prefer_structured_whatsapp,
            )
            for item in imports
        )
        if source
    ]
    return [_with_query_intent(source, query_intent) for source in sources]


def _active_whatsapp_context_source_ids(
    all_sources: list[dict[str, Any]],
    attached_sources: list[dict[str, Any]],
    selected_styles: list[dict[str, Any]],
) -> set[str]:
    source_ids = {
        _source_identity(source)
        for source in selected_styles
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    }
    source_ids.update(
        _source_identity(source)
        for source in attached_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    )
    source_ids.update(
        _source_identity(source)
        for source in all_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    )
    return {source_id for source_id in source_ids if source_id}


def _structured_whatsapp_context_source(
    whatsapp_import: dict[str, Any],
    user_text: str,
    user_id: str | None,
    *,
    conversation_fuel: bool = False,
) -> dict[str, Any] | None:
    import_id = str(whatsapp_import["id"])
    memory = retrieve_whatsapp_memory(import_id, user_id)
    chunks = memory["chunks"]
    people = memory["people"]
    style_profiles = memory["style_profiles"]
    if not chunks and not style_profiles and not people:
        return None

    selected_sender = str(whatsapp_import.get("selected_sender") or "")
    ranked_chunks = _rank_whatsapp_chunks(chunks, user_text)
    chunk_limit = (
        WHATSAPP_FUEL_RETRIEVAL_LIMIT if conversation_fuel else WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT
    )
    content = _structured_whatsapp_context_text(
        whatsapp_import,
        people,
        style_profiles,
        ranked_chunks[:chunk_limit],
        selected_sender,
        conversation_fuel=conversation_fuel,
    )
    return {
        "source_type": WHATSAPP_STRUCTURED_SOURCE_TYPE,
        "title": f"Structured WhatsApp context: {whatsapp_import.get('title') or 'import'}",
        "content": content,
        "metadata": {
            "context_source_id": whatsapp_import.get("context_source_id"),
            "import_id": import_id,
            "selected_sender": selected_sender,
            "retrieved_chunk_count": min(len(ranked_chunks), chunk_limit),
            "conversation_fuel": conversation_fuel,
        },
    }


def _ordered_memory_context_sources(
    agent_behavior_sources: list[dict[str, Any]],
    durable_memory_sources: list[dict[str, Any]],
    structured_whatsapp_sources: list[dict[str, Any]],
    query_intent: ContextQueryIntent,
) -> list[dict[str, Any]]:
    if query_intent.prefer_structured_whatsapp:
        return agent_behavior_sources + structured_whatsapp_sources + durable_memory_sources
    return agent_behavior_sources + durable_memory_sources + structured_whatsapp_sources


def _with_query_intent(
    source: dict[str, Any],
    query_intent: ContextQueryIntent,
) -> dict[str, Any]:
    if not query_intent.labels:
        return source
    metadata = dict(source.get("metadata") or {})
    metadata["query_intent"] = list(query_intent.labels)
    return {**source, "metadata": metadata}


def _structured_whatsapp_context_text(
    whatsapp_import: dict[str, Any],
    people: list[dict[str, Any]],
    style_profiles: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    selected_sender: str,
    *,
    conversation_fuel: bool = False,
) -> str:
    sections = [
        "Structured WhatsApp context.",
        "Use this when the user asks about uploaded WhatsApp chat, people, topics, messages, or texting style.",
        "When marked as conversation fuel, use one small topic or recent event to continue naturally.",
        "Do not claim live WhatsApp access; answer from this stored parsed import.",
        f"Import title: {whatsapp_import.get('title') or '-'}",
        f"Selected sender: {selected_sender or '-'}",
        f"Mode: {'conversation fuel' if conversation_fuel else 'direct retrieval'}",
    ]
    if people:
        sections.extend(
            [
                "",
                "People:",
                *[
                    f"- {person['sender']} ({person['role']}): {person['message_count']} messages"
                    for person in people[:6]
                ],
            ]
        )
    if style_profiles:
        selected_profiles = _ordered_style_profiles(style_profiles, selected_sender)
        sections.extend(["", "Style adaptation guides:"])
        for profile in selected_profiles[:2]:
            sections.append(
                style_adaptation_guide(
                    profile,
                    selected=str(profile.get("sender") or "").casefold()
                    == selected_sender.casefold(),
                )
            )
        sections.extend(["", "Sender style profile metrics:"])
        for profile in selected_profiles[:4]:
            summary = profile.get("summary") or {}
            terms = ", ".join(summary.get("topic_terms") or summary.get("frequent_terms") or [])
            samples = "; ".join(
                str(sample) for sample in (profile.get("sample_messages") or [])[:3]
            )
            sections.append(
                "- "
                f"{profile['sender']}: avg_words={summary.get('average_words')}; "
                f"short={summary.get('short_message_share')}; "
                f"questions={summary.get('question_share')}; "
                f"topics={terms or 'not enough signal'}; "
                f"samples={samples or 'not enough signal'}"
            )
    if chunks:
        sections.extend(["", "Relevant message chunks:"])
        for chunk in chunks:
            sections.append(str(chunk.get("content") or ""))
    return "\n".join(sections)


def _should_retrieve_whatsapp_conversation_fuel(user_text: str) -> bool:
    terms = memory_terms(user_text)
    if not terms:
        return False
    if len(terms) <= 4 and not _should_retrieve_memory(user_text):
        return False
    normalized = normalized_memory_text(user_text)
    return normalized in {
        "batao",
        "tell",
        "continue from whatsapp",
        "continue from uploaded chat",
        "uploaded chat se batao",
        "whatsapp se batao",
    }


def _ordered_style_profiles(
    style_profiles: list[dict[str, Any]],
    selected_sender: str,
) -> list[dict[str, Any]]:
    if not selected_sender:
        return style_profiles
    selected_casefold = selected_sender.casefold()
    return sorted(
        style_profiles,
        key=lambda profile: (
            str(profile.get("sender") or "").casefold() != selected_casefold,
            str(profile.get("sender") or ""),
        ),
    )


def _rank_whatsapp_chunks(
    chunks: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    query_terms = memory_terms(user_text)
    query_embedding = build_text_embedding(user_text, query_terms)
    if not query_terms:
        return chunks[-WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT:]

    max_index = max((int(chunk.get("chunk_index") or 0) for chunk in chunks), default=1)
    wants_recent = bool(query_terms & RECENCY_QUERY_TERMS)
    scored_chunks = [
        (score, chunk)
        for chunk in chunks
        for score in [
            _whatsapp_chunk_score(
                chunk,
                query_terms,
                query_embedding,
                max_index,
                wants_recent,
            )
        ]
    ]
    scored_chunks.sort(
        key=lambda item: (
            item[0],
            int(item[1].get("chunk_index") or 0),
        ),
        reverse=True,
    )
    positive_chunks = [chunk for score, chunk in scored_chunks if score > 0.05]
    return positive_chunks or chunks[-WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT:]


def _whatsapp_chunk_score(
    chunk: dict[str, Any],
    query_terms: set[str],
    query_embedding: dict[str, Any],
    max_index: int,
    wants_recent: bool,
) -> float:
    chunk_text = normalized_memory_text(
        " ".join(
            [
                str(chunk.get("content") or ""),
                " ".join(str(term) for term in chunk.get("terms") or []),
            ]
        )
    )
    lexical_score = sum(1 for term in query_terms if term in chunk_text)
    semantic_score = cosine_similarity(query_embedding, chunk.get("embedding"))
    recency_score = (int(chunk.get("chunk_index") or 0) / max(1, max_index)) if max_index else 0
    recency_weight = 1.25 if wants_recent else 0.15
    return (semantic_score * 6) + lexical_score + (recency_score * recency_weight)


def _relevant_memory_sources(
    sources: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    if not _should_retrieve_memory(user_text):
        return []

    scored_sources = [
        (score, source)
        for source in sources
        if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
        for score in [_memory_source_score(source, user_text)]
        if score > 0
    ]
    scored_sources.sort(key=lambda item: item[0], reverse=True)
    return [source for _, source in scored_sources[:MEMORY_RETRIEVAL_LIMIT]]


def _should_retrieve_memory(user_text: str) -> bool:
    normalized = normalized_memory_text(user_text)
    return any(term in normalized for term in MEMORY_TRIGGER_TERMS) or any(
        phrase in normalized for phrase in MEMORY_TRIGGER_PHRASES
    )


def _memory_source_score(source: dict[str, Any], user_text: str) -> int:
    query_terms = memory_terms(user_text)
    if not query_terms:
        return 0
    source_text = normalized_memory_text(
        " ".join(
            [
                str(source.get("title") or ""),
                str(source.get("source_type") or ""),
                str(source.get("content") or ""),
            ]
        )
    )
    score = sum(source_text.count(term) for term in query_terms)
    source_type = source.get("source_type")
    if source_type == "llm_profile" and any(
        term in query_terms for term in {"profile", "about", "me"}
    ):
        score += 2
    if source_type == "chat_export" and any(
        term in query_terms for term in {"chat", "conversation", "topic"}
    ):
        score += 2
    return score
