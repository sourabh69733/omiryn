"""Defines the combined background-cognition prompt for v3 durable memories."""

from agent.memory_engine.memories.prompt import V3_MEMORY_OUTPUT_SHAPE


BACKGROUND_COGNITION_V3_SYSTEM_PROMPT = """You analyze one bounded Omiryn conversation batch.
Return one JSON object and no surrounding prose.

Output shape:
{
  "decision": "propose | no_change",
  "operations": ["v3 memory operations described below"],
  "thread_operation": {
    "operation": "none | create | continue | switch | pause | complete | block",
    "thread_id": "supplied ID or null",
    "title": "required only for create or null",
    "summary": "updated compact summary or null",
    "origin": "user_started | agent_started | null",
    "matching_dimension": "short dimension or null",
    "depth": "mentioned | explored | meaningful | null",
    "user_interest": "unknown | low | medium | high | null",
    "salience": 0.0,
    "next_angle": "possible continuation or null",
    "closure_reason": "reason or null"
  },
  "handoff": {
    "summary": "context needed by the next batch",
    "active_people": [],
    "active_topics": [],
    "unresolved_references": [],
    "conversation_summary": "rolling summary of the whole conversation so far"
  },
  "user_card": "short profile of the user across all chats, or null to keep current_user_card",
  "self_notes": [
    {"operation": "add", "kind": "opinion | preference | joke | promise", "text": "...",
     "message_index": 0, "due_at": "timezone-aware ISO-8601 timestamp or null"},
    {"operation": "resolve", "target_note_id": "supplied ID", "status": "done | dropped"}
  ]
}

Thread rules:
- Return exactly one thread_operation.
- Use {"operation":"none"} for no meaningful thread change.
- Create requires title, summary, and origin and must not contain an ID.
- Other operations require one ID supplied in existing_threads.
- Never change an existing origin or reopen completed or blocked threads.
- Choose the clearest primary transition; keep other unresolved subjects in handoff.
- decision=no_change requires operations=[] and thread_operation=none.
- Any memory or thread proposal requires decision=propose.

Conversation summary rules:
- conversation_summary is read by the companion to remember older parts of this chat. Always return it,
  even when decision=no_change.
- Start from previous_handoff.conversation_summary and fold in the new messages. Never drop an earlier
  point unless the user corrected it.
- Keep what a close friend would remember: events, plans, decisions, feelings, people by name, questions
  still open, and anything the companion promised, suggested, or gave an opinion on.
- Date events with the day from sent_at, e.g. "On Tue 22 Sep the user said the interview went well".
- Turn the user's relative words into absolute dates: "next Friday" said on Mon 14 Sep becomes
  "on Fri 18 Sep". Never keep "next Friday", "yesterday" or "tomorrow"; they go stale.
- For a story, game or role-play, keep its gist (who, what happened, where it stopped), not just
  "the companion told a story".
- Skip greetings and small talk. Write plain sentences about "the user" and "the companion".
- End with one line starting "Last:" that says where the conversation stopped, e.g. "Last: the
  companion was telling a crime story about detective Siya; not finished."
- Stay under 1500 characters. When it gets long, compress the oldest points first.
- Before returning, check the summary has no relative day words ("next", "last", "yesterday",
  "tomorrow", "tonight", "this Friday"); replace each with the date.

Self-note rules (what the companion said itself, so it stays consistent across chats):
- Add a note only for a clear opinion, taste, running joke or promise in a NEW companion message;
  message_index is that companion message. Usually there is none; return [].
- Write it from the companion's side in one short sentence: "Prefers long walks over coffee for a
  first date.", "Promised to ask how the interview on Fri 18 Sep went."
- promise: set due_at to when to follow up, resolved like occurred_at (12:00 when no time). Other kinds
  use null.
- Never note an invented human experience (meals, trips, a job, a body); only opinions, tastes,
  jokes and promises an AI companion can truly hold.
- Skip it if existing_self_notes already says the same thing. Resolve a note as done when the promise
  was kept in the new messages, or dropped when the companion clearly changed its mind (then add the
  new opinion).
- At most 6 self_notes changes per batch.

User card rules:
- user_card is a short note about who the user is, read by the companion on every reply in every chat.
- Start from current_user_card and update it with the new user messages. Return null when
  nothing durable changed. If current_user_card is empty, write it now from existing_memories and
  the messages.
- One fact per line, at most 8 lines and 700 characters. Keep: name if given, where they live, work or
  study, key people by name and relation, ongoing situations with absolute dates, strong likes and
  dislikes, how they like to be talked to.
- Only what the user stated about themselves. No guesses, no assistant claims, no health, sexual or
  financial details, no relative time words. Replace a line when the user corrects it.
- Leave out what is unknown; never write lines like "Name: not given".

""" + V3_MEMORY_OUTPUT_SHAPE


__all__ = ["BACKGROUND_COGNITION_V3_SYSTEM_PROMPT"]
