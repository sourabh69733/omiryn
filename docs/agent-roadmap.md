# Omiryn agent roadmap

Written 22 September 2026. Plan for making the companion feel like a real person over months of use. Each step is small, tested and reviewed before the next.

## Problems this plan fixes

1. Storytelling: the agent needs a user message for every sentence.
2. Time: it does not know when messages were sent, how long the user was away, or when something was said.
3. Template lines such as "What's on your mind today?".
4. Generic replies: no opinions, no emotion, no stable character.
5. Thin context: only 8 recent messages are kept word for word; older ones are squeezed into short fragments.

## Decisions

| Topic | Decision |
|---|---|
| Persona | One persona card per character: Annie (woman) and Kabir (man), plus Omi (neutral). Each talks in their own character. |
| Session gap | 6 hours, configurable with `AGENT_SESSION_GAP_HOURS`. |
| Timezone | Taken from the browser (IANA name, for example `Asia/Kolkata`). |
| Companion model | Stay on Llama 3.3 70B. The design must work well for a mid-size model. |
| Reply length | Keep the 35-word cap per bubble. Allow up to 3 bubbles per turn. |

## Principles

1. **One owner per concern.** Time, memory, persona and scheduling each have one source of truth.
2. **Code computes facts, the model makes judgments.** Dates, gaps and durations are calculated in code and given to the model. The model decides tone, opinion and wording.
3. **Clean context beats big context.** Sections are short, labeled and always in the same order. Memories are written as plain sentences, not JSON.
4. **Durable over in-memory.** Work that must happen later is a database job, not a Python timer.
5. **Test the conversation, not the JSON.** Every change gets a multi-turn simulated test, including fake time jumps.

## What we borrow from other systems

| System | Idea | How we use it |
|---|---|---|
| Zep / Graphiti | Two timelines: when something happened and when the system learned it. Relative dates ("next Friday") are resolved against the message's own timestamp. | Give background cognition each message's time and the user's timezone so it can resolve relative dates. Store when the user said it (message time), not extraction time. |
| Letta (MemGPT) | Always-visible core blocks (persona, human) plus a background "sleep-time" agent that rewrites them. | Persona card per character (read-only). A short "user card" always in context, rewritten by the existing background cognition. |
| Mem0 | Moved to add-only memory with time context, so "used to live in X, now lives in Y" survives. | We already keep history through supersede. Show old versions with dates when the user asks about the past. |

We will not adopt a graph database now. Postgres plus the current V3 memory is enough at this scale.

## Target design

| Layer | Responsibility |
|---|---|
| 1. Clock | Message timestamps, user timezone, current local time, gap since the last message, session start. One injectable `now()` so tests can fake time. |
| 2. Working memory | 24 recent messages word for word plus a rolling, dated summary of the whole chat written in the background. |
| 3. Long-term memory | V3 memories, formatted as plain sentences with dates ("told me on 12 Sep: ..."). Flexible selection instead of fixed per-kind caps. |
| 4. Self | Persona card per character. Agent self-notes: opinions it gave, running jokes, promises ("tell me how the interview goes"). |
| 5. Reply shaping | Up to 3 short bubbles. A question only when it is earned. A check against stock phrases and repeats of its own recent lines, with one retry. |
| 6. Initiative | One durable job table for background cognition, return greetings, promise follow-ups and story continuation. |
| 7. Evals | Simulated conversations with time jumps, graded for time accuracy, template phrases, opinion, character consistency and recall. |

Prompt order for every reply:

```text
persona card -> behavior rules -> clock -> user card -> previous session summary
-> relevant memories and threads -> current session summary -> recent messages
```

## Phases

### Phase 1: Foundations (time and context)

1. **Clock abstraction.** One injectable `now()` used by runtime, context and background code.
2. **Browser timezone.** The web app sends the IANA timezone; it is stored in user settings.
3. **Clock block.** Add current local time, day part, time since the last user message and a new-session flag to the reply context.
4. **Gap markers in history.** Insert short notes such as "(2 days later)" between messages where the gap exceeds the session gap. No per-message timestamps, because small models tend to copy them into replies.
5. **Message time in memory.** Background cognition receives each message's time and the timezone and resolves relative dates. Evidence stores the message's sent time and message ID.
6. **"When did I tell you" support.** Memory lines include the date the user said it.
7. **Bigger window.** Raise recent messages from 8 to 24. Background cognition keeps a rolling, dated summary of the whole chat (earlier sessions included); messages it covers leave the chat history. The local fragment summary remains only for messages the background job has not reached yet.
8. **Token budget.** Chat history has an estimated token cap (`AGENT_HISTORY_TOKEN_BUDGET`); long old messages are shortened, then the oldest dropped, never the newest four. Context sources keep their existing character budget.
9. **Durable job table.** Done for the idle memory flush: `agent_jobs` rows (one per kind and conversation, debounced by moving `run_after`), claimed atomically by an in-process worker that also runs at startup, with retry backoff (60s, 120s, then failed). Phase 4 follow-ups and story parts will use the same table.
   Deployment note: on Cloud Run with `min_instance_count = 0` and default CPU throttling, the worker only runs while the instance serves traffic. Jobs are no longer lost, but may wait until the next request. For timely jobs, set `cpu_idle = false` with a minimum instance, or have Cloud Scheduler call a small job-runner endpoint.

### Phase 2: Voice and character

1. Persona cards for Annie, Kabir and Omi (`prompt_engine/personas/*.md`): vibe, voice, gendered Hindi grammar, tastes, opinions, humor, honesty limits, plus shared usage rules and stock lines to avoid. System prompt cap raised to 24000 chars; at 12000 the tone, output-format and memory-usage sections were being cut.
2. Multi-bubble replies: split on a blank line, at most 3, with typing delays.
3. Anti-template check: banned phrase list plus overlap with the agent's own last 20 replies; regenerate once if hit.
4. Question policy: react or share an opinion first; ask only when it moves the conversation forward.

### Phase 3: Memory quality

1. Plain-sentence memory formatting with dates.
2. Flexible selection instead of fixed per-kind caps; review relevance floors.
3. User card: a short always-visible summary, rewritten in the background.
4. Agent self-notes: opinions, jokes, promises, with the same lifecycle rules as memories.
5. Maintenance: embedding retry, skip unchanged content, remove orphan embeddings and reviews on conversation deletion.

### Phase 4: Initiative

1. Return greetings after a long gap, using the clock and the user's context.
2. Promise follow-ups scheduled at the right time.
3. Story mode: parts every 30 to 90 seconds, check-ins every few parts, pause when the user goes quiet, stop on request.

## Evaluation per phase

| Phase | Must pass |
|---|---|
| 1 | Correct answers to "when did I tell you X" and "how long since we talked" after fake time jumps. Relative dates resolved correctly. |
| 2 | Annie and Kabir stay in character across 30 turns. No banned phrases. Fewer questions per turn than today. |
| 3 | Recall of relevant memories without unrelated ones. Promises and opinions remembered across sessions. |
| 4 | Follow-ups arrive on time. Story mode continues, checks in and stops correctly. |

## Sources

- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)
- [Letta memory blocks](https://docs.letta.com/guides/agents/memory-blocks)
- [Letta sleep-time compute](https://www.letta.com/blog/sleep-time-compute/)
- [Mem0 add-only memory migration](https://docs.mem0.ai/migration/platform-v2-to-v3)
