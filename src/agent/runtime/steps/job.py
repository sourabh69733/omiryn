"""What every reply step shares: the history the model reads, how to call it, and the turn's facts.

Steps call the model only through `generate`, so the orchestrator decides which client they use
(and tests can swap it in one place).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .visible import visible_reply

Generate = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class ReplyJob:
    reply_messages: list[dict[str, Any]]
    generation_arguments: dict[str, Any]
    generate: Generate
    question_limit: int = 1
    user_id: str | None = None
    conversation_id: str = ""
    user_text: str = ""
    # Stored messages before this turn (not the reply window).
    history: list[dict[str, Any]] = field(default_factory=list)
    previous_replies: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    # Omi's questions in this session with what the user said next (policy.asked_questions).
    asked: list[Any] = field(default_factory=list)

    async def ask(self, note: str, messages: list[dict[str, Any]] | None = None) -> str:
        """The raw model output for the history plus one system note at the end."""
        history = self.reply_messages if messages is None else messages
        return await self.generate(history + [{"role": "system", "content": note}], **self.generation_arguments)

    async def rewrite(self, note: str, messages: list[dict[str, Any]] | None = None) -> str:
        """Like ask, but only the text the user would see."""
        return visible_reply(await self.ask(note, messages))


__all__ = ["Generate", "ReplyJob"]
