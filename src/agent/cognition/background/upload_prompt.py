"""Prompts for learning from an uploaded chat: parts read at the same time, then one merge.

An uploaded chat is two people talking, not the user talking to Omi, so it gets its own prompts
instead of the live-chat background prompt (whose "prefer no memory" rules made every part of a
real upload return nothing). A part turns its lines into structured data: topics, facts about the
user, facts about the other person, plans and how the two talk. The merge joins the parts into one
digest. Answers cite message indexes; code joins proof and dates, so the models write little.
"""

from agent.cognition.background.prompt_v3 import USER_CARD_RULES
from agent.memory_engine.memories.taxonomy import V3_MEMORY_TAXONOMY_GUIDANCE, V3_MEMORY_VALUE_GUIDANCE
from agent.memory_engine.memories.vibe import VIBE_LINE_RULES

UPLOAD_PART_SYSTEM_PROMPT = """You read one part of a chat the user uploaded: the user talking with someone
else (WhatsApp). The user shared it so their companion, Omi, gets to know them and the people in
their life. Turn this part into structured notes. Return one JSON object only.

Input: user_timezone, chat_with (the other person's name), and messages, each with i (its index),
from ("user" or the other person's name), at (local send time) and text. Messages with new=false
are only context from the part before; never cite them.

Output:
{
  "threads": [{"title": "3-6 words", "summary": "what was said, both sides, 1-2 sentences",
               "user_view": "what the user said or felt about it, or null",
               "other_view": "what the other person said or felt, or null", "lines": [i]}],
  "about_user": [<memory add operations, format below>],
  "about_other": [{"fact": "one sentence about the other person", "lines": [i]}],
  "plans": [{"what": "a plan or event", "when": "ISO-8601 date or null", "lines": [i]}],
  "dynamics": "how the two talk to each other in this part (jokes, teasing, support), or null",
  "vibe": {"<area id>": {"line": "one line", "evidence": [i of the user's own messages]}}
}

What to note:
- threads: each subject the two spent more than a line or two on. Merge small talk into nothing.
- about_user: what this part shows about the user: work, study, routine, places, people, opinions,
  likes and dislikes, frustrations, habits, plans. In a chat with a friend people reveal themselves in
  passing; that counts ("I don't trust finance influencers" is an opinion memory). Evidence is only
  the user's own messages. Keep what says something lasting; skip one-off trivia (what they ate once,
  a number from one task). Banter, "haha" and "ok" teach nothing.
- about_other: what the other person says about themselves (their work, city, views, life) or what
  the user says about them. Facts only, no judgments of their character.
- Nothing here was said to Omi: no how-to-talk requests (memory_kind procedural is never used).
- Every lines/evidence index must be a message of this part with new=true. Write only what the
  messages say. A part of only small talk returns empty lists.

Memory add operation (about_user):
{"operation": "add", "memory_kind": "semantic | episodic | relationship", "purposes": ["profile |
personalization"], "key": "short stable key", "value": "what is true, never a bare true or false",
"statement": "one short plain sentence about the user", "sensitivity": "standard | sensitive |
highly_sensitive", "confidence": 0.0-1.0, "importance": 0.0-1.0, "occurred_at": "ISO-8601 with the
user_timezone offset for a dated event, else null", "focus": false, "evidence_message_indexes": [i]}
- focus is true for something they are into for a while that will pass (studying a topic, a project,
  preparing for an exam), false for settled facts and lasting interests.
- Resolve "today", "yesterday", "next Monday" against the message's at; no relative time words in
  value or statement. Relationship history and private matters are at least sensitive; health,
  sexual and financial details are highly_sensitive.
""" + V3_MEMORY_TAXONOMY_GUIDANCE + "\n" + V3_MEMORY_VALUE_GUIDANCE + """

Vibe (who the user would get along with as a friend): vibe_areas lists the areas. Write a line only
for an area the user's own messages clearly show; most parts return {}.
""" + VIBE_LINE_RULES


UPLOAD_MERGE_SYSTEM_PROMPT = """You finish reading a chat the user uploaded with chat_with. Its parts were
read separately; merge their notes into one digest. Return one JSON object only. Refer to the notes
by their ids; code copies proof and dates from them.

Input: chat_with, chat_dates, current_user_card, existing_memories (id, statement), and the parts'
notes: candidates (memories about the user, ids c..), threads (t..), about_other (o..), plans (p..),
dynamics, vibe_areas, current_vibe and vibe_candidates (v..).

Output:
{
  "same": [["c1", "c4"]],
  "known": [{"candidate": "c2", "memory": "<existing memory id>"}],
  "threads": [{"title": "3-6 words", "summary": "1-2 sentences, both sides", "user_view": "... or null",
               "other_view": "... or null", "from": ["t1", "t5"]}],
  "person": [{"text": "one fact about chat_with", "from": ["o1", "o3"]}],
  "plans": [{"what": "...", "when": "ISO date or null", "from": ["p2"]}],
  "summary": "the whole chat in about 80 words: who, when, what they talk about, how they get on",
  "index_line": "chat_with's name and 3-5 main topics, under 15 words",
  "relationship": {"statement": "Chats with <name> on WhatsApp, mostly about <topics>.", "from": ["c3", "t1"]},
  "user_card": "the updated card, one fact per line, or null to keep current_user_card",
  "vibe": {"<area id>": {"line": "one line", "from": ["v1", "c2"]}}
}

- same: candidate ids that say the same thing about the user. known: a candidate that an existing
  memory already says. Never group different facts.
- threads: one per subject; join threads from different parts about the same subject. At most 12,
  the ones the two talked about most first.
- person: facts about chat_with, joined and without repeats; never judge their character.
- relationship.statement says who chat_with is to the user only when the notes say so.
- Write only what the notes say; a field with nothing behind it is null or [].
- user_card: when current_user_card is empty, write it from the candidates.
""" + VIBE_LINE_RULES + """

User card rules (current_user_card is the starting point; candidates are the new facts):
""" + USER_CARD_RULES


# Facts about the other person in an uploaded chat, read from the whole chat in parts. Each fact
# points at one message by index; code copies that message as the quote, so a quote is never
# written by the model.
PERSON_CARD_CATEGORIES = ("relationship", "work", "study", "home", "family", "plans", "likes", "dislikes", "other")

PERSON_CARD_SYSTEM_PROMPT = """You read part of a WhatsApp chat the user uploaded, between the user and
chat_with. List what this part says about chat_with as a person. Return one JSON object only.

Input: chat_with, and messages, each with i (its index), from ("user" or a name), at (date) and text.

Output: {"facts": [{"category": "...", "fact": "one short sentence", "line": <i of the message that says it>}]}

category is one of: relationship (partner, dating, engagement, marriage, single), work (job,
profession, employer, role, money from work), study, home (city, where they live or move), family,
plans (events, trips, goals with a time), likes, dislikes, other.

- Only what a message in this part says about chat_with: their own words about themselves, or the
  user's words about them. Not about the user, not about anyone else.
- line is the one message that says it most directly. Never a fact the line does not say; nothing
  guessed or inferred. When unsure, leave it out.
- No judgments of their character and nothing about health.
- Write the fact in plain English, keeping names, places and dates. A part with nothing about them
  returns {"facts": []}."""


# Search terms for a question about the user's past chats: the words the answer would use, which are
# often not the question's words ("relationship status" is answered by "engaged" or "shaadi").
SEARCH_QUERIES_SYSTEM_PROMPT = """The user asked their companion something whose answer may be in their past
chats (with the companion, or WhatsApp chats they uploaded, often in Hinglish). Write the short
searches that would find the lines answering it. Return one JSON object only: {"queries": ["..."]}.

Input: question, recent (the last few messages, to tell who "she" or "he" is), people (names in the
uploaded chats).

- At most 4 queries, 1-4 words each. Use the words the answer itself would contain, not the
  question's words: the specific terms, their Hinglish forms and close variants. A question about
  someone's relationship might search for engaged, shaadi, boyfriend; one about their job for job,
  naukri, office, interview.
- Put the person's first name in a query only when it would appear in the line itself.
- Nothing to search (a greeting, small talk): {"queries": []}."""


__all__ = ["PERSON_CARD_CATEGORIES", "SEARCH_QUERIES_SYSTEM_PROMPT", "PERSON_CARD_SYSTEM_PROMPT", "UPLOAD_MERGE_SYSTEM_PROMPT", "UPLOAD_PART_SYSTEM_PROMPT"]
