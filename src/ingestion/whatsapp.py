from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

WHATSAPP_IMPORT_MAX_CHARS = 1_000_000
WHATSAPP_STYLE_MAX_MESSAGES = 800
WHATSAPP_STYLE_SAMPLE_LIMIT = 10

MESSAGE_PATTERNS = [
    re.compile(
        r"^\[?(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?[Mm]\.?)?)\]?"
        r"\s[-–]\s(?P<sender>[^:]{1,120}):\s(?P<content>.*)$"
    ),
    re.compile(
        r"^\[(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?[Mm]\.?)?)\]\s"
        r"(?P<sender>[^:]{1,120}):\s(?P<content>.*)$"
    ),
]
MEDIA_MARKERS = {
    "<media omitted>",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "gif omitted",
    "document omitted",
    "this message was deleted",
    "you deleted this message",
}


@dataclass(frozen=True)
class WhatsappMessage:
    sender: str
    content: str


@dataclass(frozen=True)
class WhatsappStyleSummary:
    content: str
    metadata: dict[str, object]


def build_whatsapp_style_summary(
    export_text: str,
    user_sender: str | None = None,
) -> WhatsappStyleSummary:
    if len(export_text) > WHATSAPP_IMPORT_MAX_CHARS:
        raise ValueError(
            f"WhatsApp import is too large for v1. Limit is {WHATSAPP_IMPORT_MAX_CHARS:,} characters."
        )

    messages = parse_whatsapp_export(export_text)
    if not messages:
        raise ValueError("Could not parse WhatsApp messages. Paste a text export without media.")

    participant_counts = Counter(message.sender for message in messages)
    selected_sender = _select_sender(participant_counts, user_sender)
    user_messages = [
        message
        for message in messages
        if message.sender.casefold() == selected_sender.casefold()
        and _is_style_message(message.content)
    ][:WHATSAPP_STYLE_MAX_MESSAGES]
    if len(user_messages) < 3:
        raise ValueError("Not enough messages from that sender to learn a speaking style.")

    samples = _representative_samples(user_messages)
    lengths = [len(message.content) for message in user_messages]
    short_count = sum(1 for length in lengths if length <= 30)
    question_count = sum(1 for message in user_messages if "?" in message.content)
    exclamation_count = sum(1 for message in user_messages if "!" in message.content)
    emoji_like_count = sum(1 for message in user_messages if _has_non_ascii(message.content))
    lowercase_start_count = sum(1 for message in user_messages if _starts_lowercase(message.content))
    average_words = round(
        sum(len(message.content.split()) for message in user_messages) / len(user_messages),
        1,
    )
    frequent_terms = _frequent_terms(user_messages)
    inferred = not user_sender

    content = "\n".join(
        [
            "WhatsApp speaking-style context.",
            "Use this only to adapt Omiryn's tone, pacing, and wording to the user.",
            "Do not treat the other participant's messages as facts about the user.",
            "Do not quote private chat lines unless the user explicitly asks.",
            "",
            f"Selected user sender: {selected_sender}{' (inferred from most active sender)' if inferred else ''}",
            f"Participants: {_participants_text(participant_counts)}",
            f"Parsed messages: {len(messages)}",
            f"User messages analyzed: {len(user_messages)}",
            "",
            "Observed style signals:",
            f"- Average user message length: {round(sum(lengths) / len(lengths), 1)} characters",
            f"- Average user message size: {average_words} words",
            f"- Short-message share: {_percentage(short_count, len(user_messages))}",
            f"- Question share: {_percentage(question_count, len(user_messages))}",
            f"- Exclamation share: {_percentage(exclamation_count, len(user_messages))}",
            f"- Emoji/non-ASCII marker share: {_percentage(emoji_like_count, len(user_messages))}",
            f"- Lowercase opening share: {_percentage(lowercase_start_count, len(user_messages))}",
            f"- Frequent lightweight terms: {', '.join(frequent_terms) if frequent_terms else 'not enough signal'}",
            "",
            "Representative user style examples, redacted and shortened:",
            *[f"- {sample}" for sample in samples],
        ]
    )

    return WhatsappStyleSummary(
        content=content,
        metadata={
            "source_format": "whatsapp_text_export",
            "selected_sender": selected_sender,
            "selected_sender_inferred": inferred,
            "parsed_message_count": len(messages),
            "analyzed_user_message_count": len(user_messages),
            "participant_count": len(participant_counts),
            "import_char_count": len(export_text),
            "raw_chat_stored": False,
        },
    )


def parse_whatsapp_export(export_text: str) -> list[WhatsappMessage]:
    messages: list[WhatsappMessage] = []
    current_sender: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_sender, current_parts
        if current_sender and current_parts:
            messages.append(
                WhatsappMessage(
                    sender=current_sender.strip(),
                    content="\n".join(current_parts).strip(),
                )
            )
        current_sender = None
        current_parts = []

    for raw_line in export_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _match_message_line(line)
        if match:
            flush()
            current_sender = match.group("sender")
            current_parts = [match.group("content")]
        elif current_sender:
            current_parts.append(line)

    flush()
    return messages


def _match_message_line(line: str) -> re.Match[str] | None:
    for pattern in MESSAGE_PATTERNS:
        match = pattern.match(line)
        if match:
            return match
    return None


def _select_sender(participant_counts: Counter[str], user_sender: str | None) -> str:
    if user_sender:
        normalized = user_sender.strip().casefold()
        for sender in participant_counts:
            if sender.casefold() == normalized:
                return sender
        raise ValueError("Could not find that sender name in the WhatsApp export.")

    return participant_counts.most_common(1)[0][0]


def _is_style_message(content: str) -> bool:
    normalized = content.strip().casefold()
    if not normalized or normalized in MEDIA_MARKERS:
        return False
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return False
    return True


def _representative_samples(messages: list[WhatsappMessage]) -> list[str]:
    samples: list[str] = []
    seen: set[str] = set()
    for message in messages:
        text = _redact_private_text(" ".join(message.content.split()))
        if len(text) < 8 or text.casefold() in seen:
            continue
        samples.append(_truncate(text, 180))
        seen.add(text.casefold())
        if len(samples) == WHATSAPP_STYLE_SAMPLE_LIMIT:
            break
    return samples


def _redact_private_text(text: str) -> str:
    text = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "[email]", text)
    text = re.sub(r"https?://\S+", "[link]", text)
    text = re.sub(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b", "[phone]", text)
    return text


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _has_non_ascii(text: str) -> bool:
    return any(ord(character) > 127 for character in text)


def _starts_lowercase(text: str) -> bool:
    stripped = text.lstrip()
    return bool(stripped) and stripped[0].isalpha() and stripped[0].islower()


def _percentage(value: int, total: int) -> str:
    return f"{round((value / total) * 100)}%" if total else "0%"


def _participants_text(participant_counts: Counter[str]) -> str:
    return ", ".join(
        f"{sender} ({count})" for sender, count in participant_counts.most_common(5)
    )


def _frequent_terms(messages: list[WhatsappMessage]) -> list[str]:
    stopwords = {
        "about",
        "after",
        "again",
        "also",
        "because",
        "but",
        "can",
        "for",
        "from",
        "have",
        "just",
        "like",
        "not",
        "that",
        "the",
        "this",
        "was",
        "what",
        "when",
        "with",
        "you",
        "your",
    }
    words = Counter(
        word
        for message in messages
        for word in re.findall(r"[a-zA-Z][a-zA-Z']{2,}", message.content.lower())
        if word not in stopwords
    )
    return [word for word, _ in words.most_common(8)]
