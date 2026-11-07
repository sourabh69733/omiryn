"""Omi as host: introduces the two people of a pair, reminds them before the meet, and asks afterwards.

Code decides when something goes out and which facts it rests on (the pair, its reasons, the plan,
the dates); the reply model writes every message in Omi's own voice, in each person's own chat
with Omi, on whatever channel they use (WhatsApp, Telegram, the web app). Each step is a durable
job, so a restart loses nothing, and each one re-reads the pair before speaking: once a pair is
declined, nothing more goes out about it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from agent.context_engine.policy import split_assistant_reply
from agent.shared.clock import utc_now
from agent.shared.timeline import parse_time, relative_day, user_zone
from storage import (
    channel_link_for_user,
    get_conversation,
    get_match_pair,
    get_match_pool,
    get_user_profile,
    get_user_timezone,
    list_conversations,
    set_match_pair_plan,
    update_match_pair_plan,
)

logger = logging.getLogger(__name__)

MATCH_INTRO_JOB = "match_intro"
MATCH_REMINDER_JOB = "match_reminder"
MATCH_CHECK_IN_JOB = "match_check_in"
# Days after the meet (or the introduction, when no time was set) that Omi asks how it went, and
# days after the introduction that it asks whether they are still in touch.
CHECK_IN_DAYS = (3, 30)
# The reminder goes out the day before; a meet set up at short notice gets it three hours before.
_REMINDER_BEFORE = timedelta(days=1)
_SHORT_NOTICE_REMINDER = timedelta(hours=3)
# Pairs that are over: nothing more is said about them.
CLOSED_STATUSES = frozenset({"declined", "no_show"})
# Pairs the user may still hear about in their chat.
OPEN_STATUSES = frozenset({"introduced", "met", "still_talking"})
MAX_BUBBLES = 4

_INTRO_INSTRUCTIONS = """

INTRODUCTION
You are introducing the user to {name}, someone from {group} who also talks with you. The person
who runs their group picked the two of them, and you compared what each told you. Write the
introduction yourself, as a friend who knows both would: who {name} is to them in one line (nothing
beyond the reasons below), and why you think they would get along, in plain words, using only these
reasons:
{reasons}
{difference}{plan}
{icebreaker}They can say no, and that is fine; make that clear without pushing. Share nothing else about
{name}: not their words to you, not their notes, no contact details. Two to four short bubbles
separated by <next_message>. Do not mention scores, matching, pools, operators or being automated.
"""
_INTRO_CUE = "(The user has said nothing new. Introduce them now.)"
_PLAN_SET = "The plan so far: {place}{when}. Ask whether that works for them."
_PLAN_OPEN = (
    "No place or time is set yet: ask what evening suits them, and say you will suggest somewhere close by."
)

_REMINDER_INSTRUCTIONS = """

MEET REMINDER
The meet you set up between the user and {name} is {when_relative}: {place}{when}. If the recent chat
shows they already called it off or moved it, reply with exactly: SKIP
Otherwise remind them in one or two short bubbles, the way a friend would, and ask if they are still
on. No pressure, and do not mention reminders, timers or being automated.
"""
_REMINDER_CUE = "(The user has said nothing new. Send the reminder now.)"

_CHECK_IN_3_INSTRUCTIONS = """

HOW DID IT GO
{when_relative} the user was meant to meet {name}{place}. If the recent chat shows they already told
you how it went, or that it did not happen, reply with exactly: SKIP
Otherwise ask, lightly, how it went, in one or two short bubbles. You want to know whether they met
and whether they would see {name} again, but ask one thing at a time. No pressure, and do not
mention check-ins, timers or being automated.
"""
_CHECK_IN_30_INSTRUCTIONS = """

STILL IN TOUCH
About a month ago you introduced the user to {name}. If the recent chat shows they already told you
whether they are still in touch, or that it ended, reply with exactly: SKIP
Otherwise ask, lightly, whether they are still in touch, in one short bubble. No pressure, and do
not mention check-ins, timers or being automated.
"""
_CHECK_IN_CUE = "(The user has said nothing new. Ask them now.)"


async def introduce_pair(
    pair_id: str,
    *,
    place: str | None = None,
    when: str | None = None,
    meet_at: datetime | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Record the plan, mark the pair introduced, and queue the introduction for both people.

    `when` is the time in the operator's words ("Sunday 6pm"); `meet_at` the same as a datetime,
    when known, which times the reminder and the first check-in.
    """
    pair = get_match_pair(pair_id)
    if pair is None:
        raise LookupError("pair not found")
    if pair["status"] != "proposed":
        raise ValueError(f"pair is already {pair['status']}")
    now = utc_now()
    plan: dict[str, Any] = {
        "place": " ".join(str(place or "").split())[:160] or None,
        "when": " ".join(str(when or "").split())[:80] or None,
        "meet_at": meet_at.isoformat() if meet_at else None,
        "told": {},
        "outcomes": [],
        "set_by": created_by,
    }
    pair = set_match_pair_plan(pair_id, plan, status="introduced", introduced_at=now)
    assert pair is not None
    schedule_hosting_jobs(pair, now, meet_at)
    return pair


def schedule_hosting_jobs(pair: dict[str, Any], now: datetime, meet_at: datetime | None) -> None:
    """Queue, per person, the introduction now and the reminder and check-ins after it."""
    from agent.jobs.queue import schedule_job

    pair_id = pair["id"]
    for user_id in (pair["user_a"], pair["user_b"]):
        conversation = hosting_conversation(user_id)
        conversation_id = conversation["id"] if conversation else None
        payload = {"pair_id": pair_id}
        schedule_job(MATCH_INTRO_JOB, user_id, conversation_id, payload=payload, key=pair_id)
        for kind, run_at, extra in follow_up_times(now, meet_at):
            schedule_job(
                kind,
                user_id,
                conversation_id,
                delay_seconds=(run_at - now).total_seconds(),
                payload={**payload, **extra},
                key=f"{pair_id}:{extra.get('day', 'reminder')}",
            )


def follow_up_times(now: datetime, meet_at: datetime | None) -> list[tuple[str, datetime, dict[str, Any]]]:
    """When the reminder and the check-ins run: (job kind, time, payload extras)."""
    steps: list[tuple[str, datetime, dict[str, Any]]] = []
    if meet_at is not None and meet_at > now:
        remind_at = meet_at - _REMINDER_BEFORE
        if remind_at <= now:
            remind_at = meet_at - _SHORT_NOTICE_REMINDER
        if remind_at > now:
            steps.append((MATCH_REMINDER_JOB, remind_at, {}))
    base = meet_at if meet_at is not None and meet_at > now else now
    steps.append((MATCH_CHECK_IN_JOB, base + timedelta(days=CHECK_IN_DAYS[0]), {"day": CHECK_IN_DAYS[0]}))
    steps.append((MATCH_CHECK_IN_JOB, now + timedelta(days=CHECK_IN_DAYS[1]), {"day": CHECK_IN_DAYS[1]}))
    return steps


def hosting_conversation(user_id: str) -> dict[str, Any] | None:
    """The chat Omi hosts in: the user's WhatsApp or Telegram chat when linked, else their newest web chat."""
    rows = [
        row
        for row in list_conversations(user_id)
        if row.get("status") == "active" and not row.get("archived_at") and not row.get("temporary") and not row.get("import_source_id")
    ]
    for channel in ("whatsapp", "telegram"):
        if channel_link_for_user(user_id, channel):
            on_channel = [row for row in rows if row.get("channel") == channel]
            if on_channel:
                return _newest(on_channel, user_id)
    web = [row for row in rows if not row.get("channel")]
    return _newest(web, user_id) if web else None


def _newest(rows: list[dict[str, Any]], user_id: str) -> dict[str, Any] | None:
    newest = max(rows, key=lambda row: str(row.get("created_at") or ""))
    return get_conversation(newest["id"], user_id)


async def run_match_intro_job(job: dict[str, Any]) -> bool:
    pair = _live_pair(job)
    if pair is None or pair["status"] != "introduced":
        return False
    user_id = str(job["user_id"])
    facts = pair_facts(pair, user_id)
    check = pair.get("check") or {}
    plan = pair.get("plan") or {}
    reasons = "\n".join(f"- {reason['text']}" for reason in check.get("reasons") or []) or "- (no written reasons: say the person who runs their group thought they would get along)"
    difference = f"One difference they could live with: {check['difference']['text']}\n" if check.get("difference") else ""
    icebreaker = f"One way they could open: {check['icebreaker']}\n" if check.get("icebreaker") else ""
    instructions = _INTRO_INSTRUCTIONS.format(
        name=facts["name"],
        group=facts["group"],
        reasons=reasons,
        difference=difference,
        plan=_PLAN_SET.format(place=plan.get("place") or "somewhere close by", when=f", {plan['when']}" if plan.get("when") else "")
        if plan.get("place") or plan.get("when")
        else _PLAN_OPEN,
        icebreaker=icebreaker,
    )
    sent = await _host(user_id, pair, kind="match_intro", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_INTRO_CUE)
    now = utc_now().isoformat()

    def told(current: dict[str, Any]) -> dict[str, Any]:
        current.setdefault("told", {})[user_id] = {"at": now, "sent": sent}
        return current

    update_match_pair_plan(pair["id"], told)
    return sent


async def run_match_reminder_job(job: dict[str, Any]) -> bool:
    pair = _live_pair(job)
    if pair is None or pair["status"] != "introduced":
        return False
    user_id = str(job["user_id"])
    facts = pair_facts(pair, user_id)
    plan = pair.get("plan") or {}
    meet_at = parse_time(plan.get("meet_at"))
    if meet_at is None or meet_at <= utc_now():
        return False
    instructions = _REMINDER_INSTRUCTIONS.format(
        name=facts["name"],
        when_relative=_relative(meet_at, user_id),
        place=plan.get("place") or "the place you agreed",
        when=f", {plan['when']}" if plan.get("when") else "",
    )
    return await _host(user_id, pair, kind="match_reminder", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_REMINDER_CUE)


async def run_match_check_in_job(job: dict[str, Any]) -> bool:
    pair = _live_pair(job)
    if pair is None or pair["status"] in CLOSED_STATUSES:
        return False
    day = int((job.get("payload") or {}).get("day") or CHECK_IN_DAYS[0])
    user_id = str(job["user_id"])
    if _defer_to_daytime(job):
        return False
    facts = pair_facts(pair, user_id)
    plan = pair.get("plan") or {}
    if day >= CHECK_IN_DAYS[1]:
        instructions = _CHECK_IN_30_INSTRUCTIONS.format(name=facts["name"])
    else:
        # A user who already said they met has answered the first question; still worth asking how it went.
        meet_at = parse_time(plan.get("meet_at")) or parse_time(pair.get("introduced_at")) or utc_now()
        when_relative = _relative(meet_at, user_id)
        instructions = _CHECK_IN_3_INSTRUCTIONS.format(
            name=facts["name"],
            when_relative=when_relative[0].upper() + when_relative[1:],
            place=f" at {plan['place']}" if plan.get("place") else "",
        )
    return await _host(user_id, pair, kind=f"match_check_in_{day}", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_CHECK_IN_CUE)


def pair_facts(pair: dict[str, Any], user_id: str) -> dict[str, str]:
    """What the model may know about the other person: a first name and the group's name."""
    other_id = pair["user_b"] if pair["user_a"] == user_id else pair["user_a"]
    profile = get_user_profile(other_id) or {}
    name = str(profile.get("display_name") or "").split()
    pool = get_match_pool(pair["pool_id"]) or {}
    return {"other_id": other_id, "name": name[0] if name else "someone from your group", "group": pool.get("name") or "your group"}


def _live_pair(job: dict[str, Any]) -> dict[str, Any] | None:
    pair_id = str((job.get("payload") or {}).get("pair_id") or "")
    pair = get_match_pair(pair_id) if pair_id else None
    if pair is None or str(job["user_id"]) not in (pair["user_a"], pair["user_b"]):
        return None
    return pair


def _defer_to_daytime(job: dict[str, Any]) -> bool:
    """A check-in outside the user's daytime waits for their next morning; True when it was moved."""
    # Imported here: the proactive package imports the context engine, which reaches this module.
    from agent.jobs.queue import schedule_job
    from agent.proactive.policy import REACH_OUT_HOURS, reach_out_hours

    user_id = str(job["user_id"])
    now = utc_now()
    zone = user_zone(get_user_timezone(user_id))
    if reach_out_hours(now, zone):
        return False
    local = now.astimezone(zone)
    start = local.replace(hour=REACH_OUT_HOURS.start, minute=0, second=0, microsecond=0)
    if local.hour >= REACH_OUT_HOURS.stop:
        start += timedelta(days=1)
    payload = dict(job.get("payload") or {})
    schedule_job(
        str(job["kind"]),
        user_id,
        job.get("conversation_id"),
        delay_seconds=(start - local).total_seconds(),
        payload=payload,
        key=f"{payload.get('pair_id')}:{payload.get('day', 'reminder')}",
    )
    return True


def _relative(moment: datetime, user_id: str) -> str:
    zone = user_zone(get_user_timezone(user_id))
    return relative_day(moment.astimezone(zone).date(), utc_now().astimezone(zone).date())


async def _host(user_id: str, pair: dict[str, Any], *, kind: str, user_text: str, instructions: str, cue: str) -> bool:
    """Write one hosting message in the user's chat with Omi and push it there; False when nothing went out."""
    # Imported here: the proactive service imports the context engine, which imports this package.
    from agent.proactive.service import deliver_messages, generate_initiative_text

    conversation = hosting_conversation(user_id)
    if conversation is None:
        logger.info("agent.hosting.no_chat kind=%s pair_id=%s", kind, pair["id"])
        return False
    text = await generate_initiative_text(
        conversation, user_id, user_text=user_text, instructions=instructions, cue=cue, max_tokens=500, show_typing=False
    )
    bubbles = [bubble for bubble in split_assistant_reply(text or "", user_text="") if bubble.strip()][:MAX_BUBBLES]
    if not bubbles:
        return False
    now = utc_now().isoformat()
    new_messages = [
        {"role": "assistant", "content": bubble, "proactive": True, "proactive_kind": kind, "match_pair_id": pair["id"], "created_at": now}
        for bubble in bubbles
    ]
    # The user may write while the model works; the count check inside deliver_messages then
    # fails, and the message is added after what they wrote.
    for _ in range(3):
        if await deliver_messages(user_id, conversation["id"], expected_count=len(conversation["messages"]), new_messages=new_messages):
            break
        conversation = get_conversation(conversation["id"], user_id)
        if conversation is None:
            return False
    else:
        return False
    return True


__all__ = [
    "CHECK_IN_DAYS",
    "CLOSED_STATUSES",
    "MATCH_CHECK_IN_JOB",
    "MATCH_INTRO_JOB",
    "MATCH_REMINDER_JOB",
    "OPEN_STATUSES",
    "follow_up_times",
    "hosting_conversation",
    "introduce_pair",
    "pair_facts",
    "run_match_check_in_job",
    "run_match_intro_job",
    "run_match_reminder_job",
    "schedule_hosting_jobs",
]
