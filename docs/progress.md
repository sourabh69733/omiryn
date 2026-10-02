# Omiryn progress

Last updated 2 October 2026. Where the product, the agent and the app stand, what is decided, and what comes next. Details live in the linked docs; this page is the map.

## 1. The idea (locked)

> Omiryn: an AI you talk to that finds friends you'd actually get along with.

- The AI is the doorway; the human match is the product.
- Vibe means who you can accept in your life (humor, beliefs, values, stories you relate to, differences you can live with), not people who are merely similar.
- Friends first. Dating, marriage and family are fine to talk about when the user brings them up, but matches are friends and the companion never flirts with the user.
- Launch audience (tech college students) is an internal go-to-market choice only. It stays out of prompts, mission and product copy.

Working principles:

| Principle | What it means in practice |
|---|---|
| No hardcoding | No scripted questions, canned lines, fixed flows or keyword rules deciding what the companion does. Give the model goals and facts; let it decide. |
| Code computes facts, the model judges | Times, gaps, sessions, counts and limits come from code. Tone, wording, topics and timing come from the model. |
| Grounded data | Anything used for matching must be traceable to what the user actually said. Missing is better than wrong. |
| Evals | Only technical checks are automated. Reply quality (warmth, fun) goes to human review later ([reply-quality-review-plan.md](reply-quality-review-plan.md)). |

## 2. Persona

- One companion, **Omi**, a gender-neutral AI. No human backstory; says it is an AI when asked.
- Talks like a girl or a boy only when the user asks (hidden `<voice:...>` marker; stored per chat). The old Annie and Kabir chats map to female and male.
- Models: replies on Llama 3.3 70B (DeepInfra), fallback `Meta-Llama-3.1-70B-Instruct-Turbo` after a 25 s timeout. Vibe proof check on DeepSeek V3.2 (`VIBE_VERIFY_MODEL`).

## 3. Agent architecture (pipeline v3, prompt v3-1)

Everything below runs only with `AGENT_PIPELINE_VERSION=v3`. The code default is still `v2` (`src/agent/config.py`), and so are `.env.example`, `scripts/gcp/gcp-env.example` and the deploy scripts (`gcp-deploy.sh`, `gcp-sync-cloud-run-env.sh`). A deploy that does not set it runs v2: no vibe card, user card, self-notes or session log. The prompt default is v3-1.

```text
user message
  -> reply path (foreground)
       context engine: time notes, sessions, user card, memories, threads, Friend Vibe
       -> planner -> prompt -> model -> reply checks (questions, stock phrases) -> bubbles
  -> background cognition (every few messages or when idle)
       one model call per batch: memories, thread, session log, summary,
       user card, self-notes, vibe lines
       -> vibe proof check (second call) -> saved
  -> initiative: return greetings, promise follow-ups and nudges, story parts
```

### Built

| Area | State |
|---|---|
| Time | Message times, user timezone from the browser, time notes on messages ("(Sat 26 Sep, 5:13 pm)"), sessions shown as spans. Honesty rule: never guess a time or fact. |
| Working memory | Recent messages, the previous session's tail, a session log (gist and what was left open per session), a rolling dated summary. Fixes "forgot the last topic". |
| Long-term memory | V3 memories as plain sentences with evidence and dates. Embedding retrieval. User card (always in context) and self-notes (the companion's own opinions and promises). |
| Stories | The model marks story replies with a hidden `<story>` marker; stories continue and autoplay in parts. No keyword detection. |
| Proactive | Story parts and the background memory flush run on the durable job table. The greeting on return is a delayed in-process task started when the chat connects; promise follow-ups and nudges run in an in-process loop for users who are online. Typing dots go over realtime. |
| Reply failures | The user message is saved first. A failed reply shows "Not delivered · Retry"; fallback model on timeout. |
| Prompt | Friends-first v3 base prompt, standalone. v1 and v2 (dating era) moved to `_archive/agent/behavior_versions/`. |
| Topics | Keyword topic picker removed. The active subject comes from the background model's threads; fresh angles on a low-energy turn come from the open vibe areas. |
| Reply checks | A draft that uses a stock phrase (learned from chats plus a seed list), repeats an earlier reply, or asks too many questions gets one rewrite; extra questions are then trimmed. |

### Friend Vibe (the matching data)

The core of the product: what Omi understands about who the user would get along with.

- **11 areas.** Basics: what they want in a friend, humor, social energy, what they love, their days. Deeper: values and beliefs, stories that shaped them, differences they accept, deal-breakers, conflict, keeping in touch.
- **Written by the background model** as one or two plain English sentences per area, only from what the user said. Never from the companion's messages, never health, sexual or financial details, never dating preferences as friend preferences.
- **Proof on every line.** Each line cites the user messages behind it.
  1. Code checks each cited message is a real user message.
  2. A second model call (DeepSeek V3.2) sees each line with only its cited messages and keeps just the ones that really show it. Unproven lines are dropped; a failed check saves nothing.
- **Strength by days.** A line is solid only when said on 2 or more different days ("Said on 2 days"); otherwise "Said once" or "Said 3 times, one day".
- **Milestones:** First impressions (any 2 lines) -> The basics -> Ready to match -> Deep. Every step after the first counts only solid lines.
- **In chat:** the companion gets the goal ("understand who they'd get along with, by being good company, never by interviewing"), what it knows, what is open and fresh milestone news. Never two areas in one reply, never right after a dodge, mood always first.
- **Backfill** for older chats: `scripts/backfill_vibe_cards.py` (dry run by default, `--apply`, `--force`, `--show`; skips eval and test accounts).

## 4. App (web) state

| Screen | State |
|---|---|
| Signup | One screen: name, approximate location ("Around Kolkata, West Bengal · Change", from the IP via DB-IP Lite, dropped when the browser timezone is in another country), 18+ checkbox. Everything else is learned in chat. |
| Chat | Omi with typing dots, bubble reveal, Retry on failed messages, "Talks like" setting, milestone note ("Omi knows what you want in friends · See your vibe"). |
| Vibe | Milestone path, each area's line with a chip ("Said on 2 days"). Tap the chip for the user's own messages, each with "Open in chat". "Not right" removes a line. |
| Memories | Renamed from Style ("What Omiryn remembers"); `/style` redirects. Legacy signals hidden (data kept for export and deletion). |
| Matches | Coming soon, plus how close the user is ("Matches need Ready to match") and a link to Vibe. |
| Profile and Contact | Profile without "Interested in". Contact moved into the account menu. |

Navigation: Chat, Vibe, Memories, Matches. Contact and Profile live in the account menu.

## 5. Quality and checks

- Unit suite: about 950 backend tests and 28 web tests, independent of the developer `.env`.
- Memory evals with the real model: all 5 vibe grounding scenarios pass (small talk fills nothing, companion views never count, health and dating stay out, Hinglish filler fills nothing, only what the user showed).
- Companion vibe scenarios (no interviewing, a dodge is respected, mood first) are written but not yet run with the real model.

## 6. Next

| # | Item | Why |
|---|---|---|
| 0 | Make v3 the default pipeline | Code, `.env.example` and the deploy scripts still default to v2; check the Cloud Run setting too. |
| 1 | Backfill `--reset` | `--force` merges into old cards, so padded lines from before the proof check stay. |
| 2 | Friends-first memories | Memory rules and evals still treat partner preferences as matching data. |
| 3 | Empty user card and self-notes | Check the pipeline version first (v2 writes neither); then the debug record, with the owner's OK. |
| 4 | Embedding per vibe line | Lets matching shortlist people quickly. |
| 5 | Run the companion vibe evals and the full memory evals | Confirms the recent changes with the real model. |

## 7. Parked

- Meaning-based turn understanding, step 2: remove the keyword intent, emotion and stance rules and let the reply model read them. Run before-and-after evals first; Llama 3.3 may drift on requests made several turns back.
- VPN detection for the location estimate (DB-IP ASN file), and a "use my exact location" button.
- Human pairwise review of reply quality.
- A stronger reply model (DeepSeek V4 or Qwen 3.x are available on the account).

## 8. Not agent work (product)

- Friend compatibility check: compare two vibe cards.
- Matching: candidate pool, shortlist, both sides accept, introduction in chat.

## Related docs

- [agent-roadmap.md](agent-roadmap.md): the phase plan for time, memory, persona and initiative.
- [friends-first-audit.md](friends-first-audit.md): where the old dating idea lived and how each piece moved.
- [agent-onboarding-plan.md](agent-onboarding-plan.md): first chat and new-user stages.
- [reply-quality-review-plan.md](reply-quality-review-plan.md): human review instead of AI taste judges.
- [architecture.md](architecture.md) and [api-contract.md](api-contract.md): system and API reference.
