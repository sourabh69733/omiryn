"""Ask Omi the ability questions through the real reply path, and mark each reply.

Each question goes through `run_agent_turn`, the same code a real message takes, for a made-up
user in a fresh chat. What the person "said earlier" is put in the chat first, so these questions
test using what Omi knows, not finding it (the memory evals test finding). A follow-up is asked in
the same chat right after the question it follows.

Marking has two parts:
- Facts code can see: was there a reply, which tools ran, and did it look things up when it had to
  (or when it should not have). The tool calls and what they returned are recorded here, because
  the turn trace keeps no content.
- A judge model reads the question, what a right reply does, what the tools returned and the reply,
  and marks it right, partly or wrong with one reason. It checks the reply against the written
  rule and against what Omi actually read; it does not judge taste. Every reply is in the report,
  so a person can overrule any mark.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.evals.abilities.questions import NEEDS, QUESTIONS, WHO, AbilityQuestion
from agent.shared.clock import utc_now

TIMEZONE = "Asia/Kolkata"
JUDGE_KIND = "ability_judge"
NOTE_CHARS = 3000
# What a made-up Omi line says after the person tells it something, so the chat reads as a real one.
_HEARD = "achha, yaad rakhunga."
_LOOK_UP_TOOLS = {"web_search", "find_places"}

VERDICTS = ("right", "partly", "wrong")
REASONS = {
    "ok": "Right",
    "did_not_search": "Did not look it up",
    "searched_needlessly": "Looked it up when it should have just answered",
    "read_too_little": "Looked it up, but what it read did not hold the answer",
    "wrong_fact": "What it read held the answer, but the reply says it wrong",
    "made_up": "Stated facts it had no source for",
    "pretended": "Said it did or will do something it cannot",
    "missed_the_ask": "Did not do what was asked",
    "no_reply": "No reply",
    "not_run": "Not run",
}

JUDGE_PROMPT = (
    "You mark one reply from Omi, a personal agent that chats in short messages, mostly Hinglish.\n"
    "You get: today's date, who is asking, the question, anything the person said earlier, what a "
    "right reply does (the rule), the tools Omi called with what each returned, and Omi's reply.\n"
    "Mark the reply against the rule only. Do not judge style, warmth or length unless the rule "
    "names them. Take the rule part by part: a part counts only when the reply says it in words. "
    "Something the reply only implies does not count.\n"
    "Facts: a date, price, score, name of an opening, or news item counts as supported only when "
    "it is in what the tools returned, in what the person said, or is stable common knowledge. "
    "Compare dates with today's date.\n"
    'Return JSON: {"parts": [{"part": a part of the rule, "met": true or false}], "verdict": "right" | '
    '"partly" | "wrong", "reason": one key below, "note": one short plain sentence saying what the '
    "reply did}. List the parts first, then decide. A part is met only when the reply says it; "
    '"implies" means false.\n'
    "Reasons:\n"
    "- ok: the reply does what the rule says.\n"
    "- read_too_little: Omi looked it up, but what the tools returned does not hold the answer, "
    "so the reply could not give it (it said so, or it stayed vague).\n"
    "- wrong_fact: what the tools returned holds the answer, but the reply states it wrong or "
    "treats a past date as coming up.\n"
    "- made_up: the reply states a specific fact that is not supported.\n"
    "- pretended: the reply says Omi did, can or will do something the rule says it cannot.\n"
    "- missed_the_ask: the reply does not do what was asked: no clear view where the rule wants "
    "one, a list where it wants one step, several questions back, or it answers something else.\n"
    'Use "partly" when the main thing is right and one part of the rule is missed. Use "ok" only '
    'with "right".'
)


@dataclass(frozen=True)
class ToolUse:
    name: str
    arguments: dict[str, Any]
    returned: str


@dataclass(frozen=True)
class Asked:
    question: AbilityQuestion
    reply: str = ""
    tools: tuple[ToolUse, ...] = ()
    seconds: float = 0.0
    error: str = ""
    # The chat after this turn, for a follow-up to continue.
    conversation_id: str = ""
    messages: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Mark:
    verdict: str
    reason: str
    note: str = ""
    by: str = "code"


_tools_seen: ContextVar[list[ToolUse] | None] = ContextVar("ability_tools_seen", default=None)
_recording_installed = False


def record_tool_calls() -> None:
    """Keep every tool call of a turn, with what it returned. Installed once; a no-op outside `ask`."""
    global _recording_installed
    if _recording_installed:
        return
    from agent.tools import loop

    original = loop.run_calls

    async def recording(calls: list[Any], context: Any) -> list[Any]:
        results = await original(calls, context)
        seen = _tools_seen.get()
        if seen is not None:
            seen.extend(ToolUse(call.name, dict(call.arguments), str(result.note)) for call, result in zip(calls, results))
        return results

    loop.run_calls = recording
    _recording_installed = True


def chat_before(question: AbilityQuestion) -> list[dict[str, Any]]:
    """The chat as it stands before the question: what the person said earlier, a little while ago."""
    if not question.earlier:
        return []
    at = utc_now() - timedelta(minutes=25)
    return [
        {"role": "user", "content": question.earlier, "created_at": at.isoformat()},
        {"role": "assistant", "content": _HEARD, "created_at": (at + timedelta(minutes=1)).isoformat()},
    ]


def message_text(question: AbilityQuestion) -> str:
    return f"{question.text}\n\n{question.pasted}" if question.pasted else question.text


async def ask(user_id: str, question: AbilityQuestion, *, model: str | None, before: Asked | None = None) -> Asked:
    """One question through the real reply path. `before`: the question this one follows."""
    from agent.runtime.orchestrator import run_agent_turn
    from storage import save_conversation

    record_tool_calls()
    history = [dict(message) for message in before.messages] if before else chat_before(question)
    conversation_id = before.conversation_id if before else f"{user_id}-{question.id}-{uuid4().hex[:6]}"
    if not before:
        save_conversation({"id": conversation_id, "status": "active", "messages": history}, user_id)
    seen: list[ToolUse] = []
    token = _tools_seen.set(seen)
    started = time.perf_counter()
    try:
        turn = await run_agent_turn(
            conversation_id=conversation_id,
            messages=history,
            user_text=message_text(question),
            user_id=user_id,
            user_profile={"display_name": "Aarav", "timezone": TIMEZONE},
            model=model,
            agent_mode="know_me",
            agent_tone="auto",
            style_source_id=None,
            agent_name="Omi",
        )
    except Exception as error:
        return Asked(question, tools=tuple(seen), seconds=time.perf_counter() - started, error=f"{type(error).__name__}: {error}"[:200], conversation_id=conversation_id, messages=tuple(history))
    finally:
        _tools_seen.reset(token)
    new = turn.messages[len(history):]
    reply = "\n".join(str(message.get("content") or "") for message in new if message.get("role") == "assistant").strip()
    return Asked(question, reply, tuple(seen), time.perf_counter() - started, conversation_id=conversation_id, messages=tuple(turn.messages))


def code_mark(asked: Asked) -> Mark | None:
    """What code alone can decide. None: the judge has to read it."""
    question = asked.question
    if asked.error or not asked.reply:
        return Mark("wrong", "no_reply", asked.error or "Omi sent nothing.")
    looked_up = any(tool.name in _LOOK_UP_TOOLS for tool in asked.tools)
    if question.search is True and not looked_up:
        return Mark("wrong", "did_not_search", "This changes over time, and Omi answered without looking it up.")
    return None


def final_mark(asked: Asked, judged: Mark | None) -> Mark:
    decided = code_mark(asked)
    if decided is not None:
        # The judge's reading is kept beside it: the reply may have made something up, or been right by luck.
        note = f"{decided.note} Judge read the reply as {judged.verdict}: {judged.note}" if judged else decided.note
        return Mark(decided.verdict, decided.reason, note, "code")
    if judged is None:
        return Mark("wrong", "not_run", "No judge ran, so this needs a person to read it.")
    searched = any(tool.name == "web_search" for tool in asked.tools)
    if asked.question.search is False and searched and judged.verdict == "right":
        return Mark("partly", "searched_needlessly", judged.note, "code")
    return judged


def judge_input(asked: Asked, *, today: datetime | None = None) -> str:
    question = asked.question
    now = (today or utc_now()).astimezone(ZoneInfo(TIMEZONE))
    return json.dumps(
        {
            "today": now.strftime("%A, %d %B %Y, %H:%M India time"),
            "who_is_asking": WHO[question.who],
            "said_earlier": question.earlier,
            "question": message_text(question),
            "asked_right_after": question.after,
            "omi_can_do_this_today": question.can_today,
            "what_it_needs": NEEDS[question.needs],
            "rule_a_right_reply": question.right_when,
            "tools_called": [
                {"tool": tool.name, "arguments": tool.arguments, "returned": tool.returned[:NOTE_CHARS]} for tool in asked.tools
            ],
            "omi_reply": asked.reply,
        },
        ensure_ascii=False,
        indent=1,
    )


def parse_judgment(raw: dict[str, Any]) -> Mark | None:
    verdict = str(raw.get("verdict") or "").strip().lower()
    reason = str(raw.get("reason") or "").strip().lower()
    if verdict not in VERDICTS or reason not in REASONS or reason in {"no_reply", "not_run", "did_not_search", "searched_needlessly"}:
        return None
    # Judges mix the two up ("partly" with "ok"): the verdict wins, and a reply that is not right
    # with no reason named has missed part of what was asked.
    if verdict != "right" and reason == "ok":
        reason = "missed_the_ask"
    if verdict == "right" and reason != "ok":
        verdict = "partly"
    note = " ".join(str(raw.get("note") or "").split())[:300]
    parts = [part for part in raw.get("parts") or [] if isinstance(part, dict)]
    missed = [" ".join(str(part.get("part") or "").split()) for part in parts if part.get("met") is False]
    if verdict == "right" and missed:
        # The judge's own list says a part of the rule is missing, so it cannot be fully right.
        return Mark("partly", "missed_the_ask", f"Missing: {'; '.join(missed)[:200]}. {note}".strip(), "judge")
    return Mark(verdict, reason, note, "judge")


async def judge(asked: Asked, *, model: str | None = None) -> Mark | None:
    """The judge's mark, or None when it could not be read (after one more try)."""
    from agent.providers.extraction.service import request_check_model
    from agent.providers.gateway.router import provider_chat
    from agent.providers.shared.config import agent_runtime_status
    from agent.providers.shared.json_utils import _parse_json_object

    provider = str(agent_runtime_status().get("provider") or "")
    for _ in range(2):
        try:
            raw = await provider_chat(
                provider=provider,
                system_prompt=JUDGE_PROMPT,
                messages=[{"role": "user", "content": judge_input(asked)}],
                temperature=0,
                # The test user's own chat, so the judge's cost is counted with the run.
                conversation_id=asked.conversation_id or None,
                request_kind=JUDGE_KIND,
                model=model or request_check_model(provider),
                timeout_seconds=40,
                response_format={"type": "json_object"},
            )
            mark = parse_judgment(_parse_json_object(raw))
        except Exception:
            mark = None
        if mark is not None:
            return mark
    return None


def chains(questions: list[AbilityQuestion]) -> list[list[AbilityQuestion]]:
    """Questions grouped so a follow-up runs after the one it follows, in the same chat."""
    by_id = {question.id: question for question in QUESTIONS}
    picked = {question.id for question in questions}
    groups: dict[str, list[AbilityQuestion]] = {}
    for question in questions:
        if question.after:
            # A follow-up needs its first question, picked or not.
            groups.setdefault(question.after, [by_id[question.after]])
            groups[question.after].append(question)
        else:
            groups.setdefault(question.id, [question])
    return [group for head, group in groups.items() if head in picked or len(group) > 1]


async def run(
    questions: list[AbilityQuestion],
    *,
    model: str | None,
    use_judge: bool = True,
    judge_model: str | None = None,
    at_once: int = 4,
    on_done: Callable[[Asked, Mark], None] | None = None,
    ask_one: Callable[..., Awaitable[Asked]] = ask,
) -> list[tuple[Asked, Mark]]:
    """Every question asked and marked, in the order of the list."""
    from storage import set_user_timezone

    gate = asyncio.Semaphore(max(1, at_once))
    done: dict[str, tuple[Asked, Mark]] = {}

    async def one_chain(group: list[AbilityQuestion]) -> None:
        async with gate:
            user_id = f"ability-{uuid4().hex[:8]}"
            set_user_timezone(user_id, TIMEZONE)
            before: Asked | None = None
            for question in group:
                if not question.runnable:
                    asked, mark = Asked(question), Mark("wrong", "not_run", "The test cannot send this.")
                else:
                    asked = await ask_one(user_id, question, model=model, before=before)
                    judged = await judge(asked, model=judge_model) if use_judge and asked.reply else None
                    mark = final_mark(asked, judged)
                    before = asked
                done[question.id] = (asked, mark)
                if on_done:
                    on_done(asked, mark)

    await asyncio.gather(*(one_chain(group) for group in chains(questions)))
    wanted = {question.id for question in questions}
    return [done[question.id] for question in QUESTIONS if question.id in done and question.id in wanted]


__all__ = [
    "Asked",
    "JUDGE_PROMPT",
    "Mark",
    "REASONS",
    "ToolUse",
    "ask",
    "chains",
    "chat_before",
    "code_mark",
    "final_mark",
    "judge",
    "judge_input",
    "parse_judgment",
    "run",
]
