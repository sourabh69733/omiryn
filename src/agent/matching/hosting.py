"""Omi as host: introduces the two people of a pair, reminds them before the meet, and asks afterwards.

Code decides when something goes out and which facts it rests on (the pair, its reasons, the plan,
the dates); the reply model writes every message in Omi's own voice, in each person's own chat
with Omi, on whatever channel they use (WhatsApp, Telegram, the web app). Each step is a durable
job, so a restart loses nothing, and each one re-reads the pair before speaking: once a pair is
declined, nothing more goes out about it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
MATCH_PLAN_JOB = "match_plan"
# A plan set while the introduction is still on its way waits for it, this long at a time, this often at most.
_PLAN_WAIT_SECONDS = 300.0
_PLAN_MAX_WAITS = 12
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
# Why a hosting message did not reach the person. A failed send, a chat that moved under us and a
# model that wrote nothing can all pass, so the job tries again; no chat at all will not.
NO_CHAT = "no_chat"
NOTHING_WRITTEN = "nothing_written"
CHAT_MOVED = "chat_moved"
CHANNEL_FAILED = "channel_failed"
_WORTH_ANOTHER_TRY = frozenset({NOTHING_WRITTEN, CHAT_MOVED, CHANNEL_FAILED})


class Undelivered(Exception):
    """A step that must arrive (the ask, the introduction) did not, and the job should run again."""


@dataclass(frozen=True)
class Hosted:
    """What became of one hosting message. `why` says why it did not reach the person."""

    sent: bool
    why: str | None = None
    # Of a message stored in a WhatsApp or Telegram chat: how many bubbles went out before a send was refused.
    bubbles_out: int = 0

_INTRO_INSTRUCTIONS = """

INTRODUCTION
You are introducing the user to {name}, someone from {group} who also talks with you. The person
who runs their group picked the two of them, and you compared what each told you. Write the
introduction yourself, as a friend who knows both would: who {name} is to them in one line (nothing
beyond the reasons below), and why you think they would get along, in plain words, using only these
reasons:
{reasons}
{difference}{plan}
{chat}{icebreaker}They can say no, and that is fine; make that clear without pushing. Share nothing else about
{name}: not their words to you, not their notes, no contact details. Two to four short bubbles
separated by <next_message>. Do not mention scores, matching, pools, operators or being automated.
"""
_INTRO_CUE = "(The user has said nothing new. Introduce them now.)"
_PLAN_SET = "The plan so far: {place}{when}. Ask whether that works for them."
_PLAN_OPEN = (
    "No place or time is set yet: ask what evening suits them, and say you will suggest somewhere close by."
)
# With the chat in the app and no plan set by the operator, the two talk first; a meet is theirs to arrange.
_PLAN_CHAT_FIRST = (
    "No meet is planned and you are not arranging one: the two get to know each other in the chat first. "
    "Do not ask about an evening or suggest a place; meeting is theirs to decide later."
)
# Said only once the app has the chat screen (MATCH_CHAT_IN_APP).
_CHAT_OPEN = (
    "The two can now write to each other directly: in the Omiryn app, under Matches, there is a chat with {name}. "
    "Tell them so. You cannot see that chat and you do not carry messages between them.\n"
)

_REMINDER_INSTRUCTIONS = """

MEET REMINDER
The meet you set up between the user and {name} is {when_relative}: {place}{when}. If the recent chat
shows they already called it off or moved it, reply with exactly: SKIP
Otherwise remind them in one or two short bubbles, the way a friend would, and ask if they are still
on. No pressure, and do not mention reminders, timers or being automated.
"""
_REMINDER_CUE = "(The user has said nothing new. Send the reminder now.)"

_PLAN_INSTRUCTIONS = """

MEET PLAN
You introduced the user to {name}. There is now a plan for the two to meet: {place}{when}. If the
recent chat shows the user already knows this plan, reply with exactly: SKIP
Otherwise tell them the plan in one or two short bubbles, the way a friend would, and ask whether it
works for them. Saying no or asking for another time is fine; make that easy. Do not mention
operators, scheduling or being automated.
"""
_PLAN_CUE = "(The user has said nothing new. Tell them the plan now.)"

_CHECK_IN_3_INSTRUCTIONS = """

HOW DID IT GO
{when_relative} the user was meant to meet {name}{place}. If the recent chat shows they already told
you how it went, or that it did not happen, reply with exactly: SKIP
Otherwise ask, lightly, how it went, in one or two short bubbles. You want to know whether they met
and whether they would see {name} again, but ask one thing at a time. No pressure, and do not
mention check-ins, timers or being automated.
"""
# The first check-in when the two talk in the app and no meet was planned.
_CHECK_IN_3_CHAT_INSTRUCTIONS = """

HOW IS IT GOING
{when_relative} you introduced the user to {name}. The two can write to each other in the app; you
cannot see that chat. If the recent chat shows they already told you how it is going with {name}, or
that it ended, reply with exactly: SKIP
Otherwise ask, lightly, how it is going with {name}, in one or two short bubbles. Do not assume they
met or push them to; ask one thing at a time. No pressure, and do not mention check-ins, timers or
being automated.
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


def set_meet_plan(pair_id: str, changes: dict[str, Any], *, created_by: str | None = None) -> dict[str, Any]:
    """Set or change where and when an introduced pair meets. This is the way to a plan for a
    pair that came through the ask: both said hi, the introduction went out with no place or
    time, and until now nothing could add one, so no reminder was ever queued.

    `changes` holds the fields to set, any of place, when (the time in words) and meet_at (a
    datetime, which times the reminder and the first check-in); a field left out stays as it is.
    Both people are told the plan in their own chat, the reminder is queued for the day before,
    and the first check-in moves to three days after the meet.
    """
    unknown = set(changes) - {"place", "when", "meet_at"}
    if unknown or not changes:
        raise ValueError("give a place, a time in words (when) or meet_at")
    now = utc_now()
    meet_at = changes.get("meet_at")
    if meet_at is not None and meet_at <= now:
        raise ValueError("meet_at is in the past")
    ran = False

    def change(plan: dict[str, Any]) -> dict[str, Any]:
        nonlocal ran
        ran = True
        if "place" in changes:
            plan["place"] = " ".join(str(changes["place"] or "").split())[:160] or None
        if "when" in changes:
            plan["when"] = " ".join(str(changes["when"] or "").split())[:80] or None
        if "meet_at" in changes:
            plan["meet_at"] = meet_at.isoformat() if meet_at else None
        plan["plan_set_at"] = now.isoformat()
        plan["plan_set_by"] = created_by
        return plan

    pair = update_match_pair_plan(pair_id, change, only_if_status="introduced")
    if pair is None:
        raise LookupError("pair not found")
    if not ran:
        raise PlanNotOpen(f"pair is {pair['status']}; a plan is set once both said hi and the pair is introduced")
    schedule_plan_jobs(pair, now)
    return pair


class PlanNotOpen(ValueError):
    """The pair is not at a stage where a plan can be set."""


def schedule_plan_jobs(pair: dict[str, Any], now: datetime) -> None:
    """After the plan changed: per person, tell them, and move the reminder and the first check-in
    to the new time. The day 30 check-in counts from the introduction and stays where it is."""
    from agent.jobs.queue import schedule_job

    pair_id = pair["id"]
    meet_at = parse_time((pair.get("plan") or {}).get("meet_at"))
    for user_id in (pair["user_a"], pair["user_b"]):
        conversation = hosting_conversation(user_id)
        conversation_id = conversation["id"] if conversation else None
        payload = {"pair_id": pair_id}
        schedule_job(MATCH_PLAN_JOB, user_id, conversation_id, payload=payload, key=f"{pair_id}:plan")
        if meet_at is None:
            continue
        for kind, run_at, extra in follow_up_times(now, meet_at):
            if extra.get("day") == CHECK_IN_DAYS[1]:
                continue
            schedule_job(kind, user_id, conversation_id, delay_seconds=(run_at - now).total_seconds(), payload={**payload, **extra}, key=f"{pair_id}:{extra.get('day', 'reminder')}")


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
        # A linked number on a channel this server has switched off reaches nobody: use the app's chat.
        if channel_link_for_user(user_id, channel) and _channel_on(channel):
            on_channel = [row for row in rows if row.get("channel") == channel]
            if on_channel:
                return _newest(on_channel, user_id)
    web = [row for row in rows if not row.get("channel")]
    return _newest(web, user_id) if web else None


def _channel_on(channel: str) -> bool:
    if channel == "whatsapp":
        from channels import whatsapp

        return whatsapp.whatsapp_enabled()
    from channels import telegram

    return telegram.telegram_enabled()


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
        else (_PLAN_CHAT_FIRST if _chat_announced() else _PLAN_OPEN),
        chat=_CHAT_OPEN.format(name=facts["name"]) if _chat_announced() else "",
        icebreaker=icebreaker,
    )
    # The note says which plan this introduction carried, so a plan set meanwhile is still told (run_match_plan_job).
    return await tell_step(
        job, pair, user_id, kind="match_intro", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_INTRO_CUE,
        note={"plan_at": plan.get("plan_set_at")},
    )


async def run_match_plan_job(job: dict[str, Any]) -> bool:
    """Tell one person the plan that was set after the introduction. Nothing goes out when the
    introduction itself carried this plan, or when they were already told it."""
    from agent.jobs.queue import schedule_job

    pair = _live_pair(job)
    if pair is None or pair["status"] != "introduced":
        return False
    user_id = str(job["user_id"])
    plan = pair.get("plan") or {}
    if not (plan.get("place") or plan.get("when")):
        return False
    payload = dict(job.get("payload") or {})
    key = f"{pair['id']}:plan"
    told = (plan.get("told") or {}).get(user_id) or {}
    if not (told.get("sent") and told.get("step") == "match_intro"):
        # The introduction has not reached them yet. It reads the pair when it runs, so it will most
        # likely carry the plan; look again after it, in case it had already read the pair.
        waits = int(payload.get("waits") or 0)
        if waits < _PLAN_MAX_WAITS:
            schedule_job(MATCH_PLAN_JOB, user_id, job.get("conversation_id"), delay_seconds=_PLAN_WAIT_SECONDS, payload={**payload, "waits": waits + 1}, key=key)
        return False
    if told.get("plan_at") == plan.get("plan_set_at"):
        return False
    if _defer_to_daytime(job, key=key):
        return False
    facts = pair_facts(pair, user_id)
    instructions = _PLAN_INSTRUCTIONS.format(name=facts["name"], place=plan.get("place") or "somewhere close by", when=f", {plan['when']}" if plan.get("when") else "")
    sent = await _host(user_id, pair, kind="match_plan", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_PLAN_CUE)
    if sent:
        plan_at = plan.get("plan_set_at")

        def heard(current: dict[str, Any]) -> dict[str, Any]:
            current.setdefault("told", {}).setdefault(user_id, {})["plan_at"] = plan_at
            return current

        update_match_pair_plan(pair["id"], heard)
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
        when_relative = when_relative[0].upper() + when_relative[1:]
        if _chat_announced() and not (plan.get("place") or plan.get("when") or plan.get("meet_at")):
            instructions = _CHECK_IN_3_CHAT_INSTRUCTIONS.format(name=facts["name"], when_relative=when_relative)
        else:
            instructions = _CHECK_IN_3_INSTRUCTIONS.format(
                name=facts["name"], when_relative=when_relative, place=f" at {plan['place']}" if plan.get("place") else ""
            )
    return await _host(user_id, pair, kind=f"match_check_in_{day}", user_text=f"meeting {facts['name']}", instructions=instructions, cue=_CHECK_IN_CUE)


def _chat_announced() -> bool:
    # Imported here: pair_chat imports this module.
    from .pair_chat import chat_announced

    return chat_announced()


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


def _defer_to_daytime(job: dict[str, Any], *, key: str | None = None) -> bool:
    """A check-in outside the user's daytime waits for their next morning; True when it was moved.
    `key` is the job's own key when it is not the pair id with a day or "reminder"."""
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
        key=key or f"{payload.get('pair_id')}:{payload.get('day', 'reminder')}",
    )
    return True


def _relative(moment: datetime, user_id: str) -> str:
    zone = user_zone(get_user_timezone(user_id))
    return relative_day(moment.astimezone(zone).date(), utc_now().astimezone(zone).date())


async def tell_step(
    job: dict[str, Any], pair: dict[str, Any], user_id: str, *, kind: str, user_text: str, instructions: str, cue: str, note: dict[str, Any] | None = None
) -> bool:
    """A step that must arrive: the ask or the introduction. Writes on the pair whether it reached
    this person, so nothing else unlocks on a message nobody got.

    Not reached: the note says why, the job is run again by the worker (raise) while trying again
    can help, and after the last try the note says so (`gave_up`), with a line in the audit log, so
    the operator sees it on the pair and can send it again. A person who was already told an
    earlier step stays told: a failed introduction does not take their card away. `note` is kept
    with the note of a step that arrived (small facts, such as which plan it carried).
    """
    from agent.jobs.worker import MAX_ATTEMPTS
    from storage import record_audit_event

    before = ((pair.get("plan") or {}).get("told") or {}).get(user_id) or {}
    # The last try stored the words and the phone refused them: send the same words, from where it stopped.
    resend_from = int(before.get("bubbles_out") or 0) if before.get("failed") == CHANNEL_FAILED and before.get("failed_step") == kind else None
    hosted = await _host_report(user_id, pair, kind=kind, user_text=user_text, instructions=instructions, cue=cue, resend_from=resend_from)
    # A job run by hand carries no count: treat it as the last try.
    attempt = int(job.get("attempts") or MAX_ATTEMPTS)
    again = not hosted.sent and hosted.why in _WORTH_ANOTHER_TRY and attempt < MAX_ATTEMPTS
    now = utc_now().isoformat()

    def told(current: dict[str, Any]) -> dict[str, Any]:
        notes = current.setdefault("told", {})
        earlier = notes.get(user_id) or {}
        if hosted.sent:
            notes[user_id] = {"at": now, "sent": True, "step": kind, **(note or {})}
        else:
            notes[user_id] = {
                **({key: earlier[key] for key in ("at", "sent", "step", "plan_at") if key in earlier} if earlier.get("sent") else {"at": now, "sent": False}),
                "failed": hosted.why, "failed_step": kind, "failed_at": now, "attempts": attempt, "bubbles_out": hosted.bubbles_out, "gave_up": not again,
            }
        return current

    update_match_pair_plan(pair["id"], told)
    if hosted.sent:
        return True
    if again:
        raise Undelivered(f"{kind}: {hosted.why}")
    logger.warning("agent.hosting.undelivered kind=%s pair_id=%s why=%s attempts=%s", kind, pair["id"], hosted.why, attempt)
    record_audit_event("match.undelivered", actor_id=None, actor_role="system", target_user_id=user_id, target_id=pair["id"], detail={"step": kind, "why": hosted.why, "attempts": attempt})
    return False


def undelivered(pair: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Who the pair's last must-arrive step did not reach, and why: {user id: {"step", "why", "gave_up"}}."""
    told = (pair.get("plan") or {}).get("told") or {}
    return {
        user_id: {"step": note.get("failed_step"), "why": note["failed"], "gave_up": bool(note.get("gave_up"))}
        for user_id, note in told.items()
        if isinstance(note, dict) and note.get("failed")
    }


async def _host(user_id: str, pair: dict[str, Any], *, kind: str, user_text: str, instructions: str, cue: str) -> bool:
    """Write one hosting message in the user's chat with Omi and push it there; False when nothing reached them."""
    return (await _host_report(user_id, pair, kind=kind, user_text=user_text, instructions=instructions, cue=cue)).sent


async def _host_report(
    user_id: str, pair: dict[str, Any], *, kind: str, user_text: str, instructions: str, cue: str, resend_from: int | None = None
) -> Hosted:
    """_host, saying why when nothing reached the person. A message stored in a WhatsApp or
    Telegram chat that the app refused is not sent: the phone got nothing. With `resend_from`,
    the words an earlier try stored for this step are sent again from that bubble on, when they
    are still the last thing in the chat, so the step is not written twice."""
    # Imported here: the proactive service imports the context engine, which imports this package.
    from agent.proactive.service import deliver_messages_report, generate_initiative_text, send_bubbles_on_channel

    conversation = hosting_conversation(user_id)
    if conversation is None:
        logger.info("agent.hosting.no_chat kind=%s pair_id=%s", kind, pair["id"])
        return Hosted(False, NO_CHAT)
    if resend_from is not None:
        stored = _stored_bubbles(conversation, kind, pair["id"])
        if stored:
            reached, out = await send_bubbles_on_channel(user_id, conversation, stored[resend_from:])
            return Hosted(True) if reached else Hosted(False, CHANNEL_FAILED, resend_from + out)
    text = await generate_initiative_text(
        conversation, user_id, user_text=user_text, instructions=instructions, cue=cue, max_tokens=500, show_typing=False
    )
    bubbles = [bubble for bubble in split_assistant_reply(text or "", user_text="") if bubble.strip()][:MAX_BUBBLES]
    if not bubbles:
        return Hosted(False, NOTHING_WRITTEN)
    now = utc_now().isoformat()
    new_messages = [
        {"role": "assistant", "content": bubble, "proactive": True, "proactive_kind": kind, "match_pair_id": pair["id"], "created_at": now}
        for bubble in bubbles
    ]
    # The user may write while the model works; the count check inside deliver_messages then
    # fails, and the message is added after what they wrote.
    for _ in range(3):
        delivery = await deliver_messages_report(user_id, conversation["id"], expected_count=len(conversation["messages"]), new_messages=new_messages)
        if delivery.stored:
            break
        conversation = get_conversation(conversation["id"], user_id)
        if conversation is None:
            return Hosted(False, NO_CHAT)
    else:
        return Hosted(False, CHAT_MOVED)
    if not delivery.reached:
        logger.warning("agent.hosting.channel_failed kind=%s pair_id=%s bubbles_out=%s", kind, pair["id"], delivery.bubbles_sent)
        return Hosted(False, CHANNEL_FAILED, delivery.bubbles_sent)
    return Hosted(True)


def _stored_bubbles(conversation: dict[str, Any], kind: str, pair_id: str) -> list[str]:
    """This step's bubbles for this pair, when they are the last thing in the chat."""
    tail: list[str] = []
    for message in reversed(conversation.get("messages") or []):
        if message.get("proactive_kind") != kind or message.get("match_pair_id") != pair_id:
            break
        tail.append(str(message.get("content") or ""))
    return tail[::-1]


__all__ = [
    "CHANNEL_FAILED",
    "CHAT_MOVED",
    "CHECK_IN_DAYS",
    "CLOSED_STATUSES",
    "Hosted",
    "MATCH_CHECK_IN_JOB",
    "MATCH_INTRO_JOB",
    "MATCH_PLAN_JOB",
    "MATCH_REMINDER_JOB",
    "NOTHING_WRITTEN",
    "NO_CHAT",
    "OPEN_STATUSES",
    "PlanNotOpen",
    "Undelivered",
    "follow_up_times",
    "hosting_conversation",
    "introduce_pair",
    "pair_facts",
    "run_match_check_in_job",
    "run_match_intro_job",
    "run_match_plan_job",
    "run_match_reminder_job",
    "schedule_hosting_jobs",
    "schedule_plan_jobs",
    "set_meet_plan",
    "tell_step",
    "undelivered",
]
