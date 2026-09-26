# Agent onboarding plan (new users)

Written 26 September 2026. How the companion should start with a brand-new user. Planned as its own roadmap step (Phase 5); not built yet.

## Today

1. **Fixed first message.** Creating the first chat saves `"Hey {name}, I'm {agent}."` (`src/api/helpers.py`, `_initial_agent_message`). No model call, nothing about what Omiryn is for, and no opener, so the user has to think of something to say.
2. **No "new user" awareness.** The agent gets the wizard basics (name, age, gender, interested in, city) but not that this is the first chat, or how long it has known the user. A new user gets the same prompt as a returning one.
3. **One tracker, hidden.** "Matching understanding" (`src/agent/context_engine/assembly/matching.py`) tracks 13 areas: 5 basics (relationship intent, desired partner, age preference, location preference, desired personality) and 8 deeper ones (values, lifestyle, family expectations, communication, attraction, boundaries, relationship dynamics, flexibility). It reaches the prompt as known and not-yet-known areas, deliberately "not a checklist", and only with prompt `v3-1`. Neither admin nor the app shows it.
4. **No nudge for new users.** Proactive messages only reopen existing threads for users who are online. A new user who leaves after two messages hears nothing.

## Plan

1. **A real first message.** Generated from the user's name, local time of day and the persona. One short line saying honestly that it is an AI companion that gets to know them to find better matches, then one easy, specific opener. No generic "how's your day". Falls back to today's fixed text if the model call fails, so opening a chat never breaks.
2. **Getting-to-know-you stage in the prompt.** Computed in code from days since the first chat, user message count and how many of the 5 basics are known:

   | Stage | Rule | Guidance |
   |---|---|---|
   | new | first chat, fewer than ~10 user messages | Be warm and curious; learn a little naturally; explain what Omiryn does only if asked or once early. |
   | getting to know | some of the 5 basics still unknown | Missing basics may come up when the conversation allows. Never a questionnaire, never two basics in one reply. |
   | known | basics known | Normal behavior. |

   The stage is a soft hint. The user's mood, request and current topic always come first (same rule as matching understanding today).
3. **Admin tracker per user.** Stage, which of the 13 areas are known, days since the first chat, user message count and last active. Dashboard summary: "40 new users: 25 new, 12 getting to know, 3 known".
4. **Early drop-off nudge (with Phase 4).** A new user who goes quiet in their first days gets one light message tied to what they said, through the Phase 4 job queue and frequency limits.

## Decisions to make before building

1. **User-facing progress?** Should the user ever see something like "Omiryn knows you 40%"? The code avoids a score on purpose today. Leaning: admin only.
2. **Goal of the first chat.** Lead toward matching (collect the 5 basics early), or build the relationship first and let matching come later? This sets how strong the stage guidance is.

## Tests

- First message: uses the name and time of day, says it is an AI, has one opener, no stock phrases; falls back on provider failure.
- Stage: computed correctly from message count, days and known basics; changes the prompt guidance.
- Behavior evals: a new user's first 10 turns ask at most one basics question per reply, never two in a row, and never ignore what the user said.
- Admin: stage counts and per-user area list.
