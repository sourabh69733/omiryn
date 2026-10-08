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

Pipeline v3 is the default (`src/agent/config.py`, `.env.example`, the GCP env example and deploy scripts); v1 and v2 remain only when set explicitly. The prompt default is v3-1. `GET /health` shows the running pipeline and prompt version, so a deploy on the wrong one is seen at once. A Cloud Run service that still sets `AGENT_PIPELINE_VERSION=v2` keeps v2 until that setting is changed.

Background work and Cloud Run: the job worker, the proactive loop and the after-reply background step run inside the API process, which only gets CPU while a request is open. When the user comes back (the realtime connection opens), every chat with unprocessed messages gets a memory flush queued at once, including flushes that ran out of retries. No always-on instance is needed; a user who never returns keeps their last few messages unprocessed.

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
| Background reliability | One bad memory or handoff is dropped on its own; the rest of the batch (memories, user card, vibe, summary) is still saved. A batch that fails on its content 3 times is skipped (provider outages never count), a retried batch keeps its first saved answer, and a chat deleted mid-run is skipped quietly. Every run is recorded in an encrypted debug record, including what was dropped. |
| Concurrency | Background work runs one chat at a time per user (a user lease), so each run reads the cards and memories the last one wrote; other chats retry in a minute. Vibe card writes check the card is unchanged since they read it, else re-read and merge again. |
| Changing facts | The background model sees each memory's history (times said, days, first and last date, latest words) and replaces a memory only on a clear change; short-term states get their own memory with an end date. When unsure it can add an open question (`agent_open_questions`, 14-day expiry, one per batch); Omi sees one at a time, in up to 3 replies per session, to ask only if it fits; the user's answer resolves it, or the Memories page dismisses it. A conflicting add is skipped alone instead of failing the batch. Live tests: Qwen rarely chooses to ask and once put a trip's end date on the home memory; DeepSeek V3.2 handled the answer best. |
| Reprocessing old chats | Chats handled by the v2 pipeline are marked done, so v3 never saw them. `scripts/reprocess_memories.py` (dry run by default, `--apply`, `--user`, `--conversation`) resets their cursor and runs v3 over them. Run it once in production after moving to v3. |
| Stories | The model marks story replies with a hidden `<story>` marker; stories continue and autoplay in parts. No keyword detection. |
| Proactive | Story parts and the background memory flush run on the durable job table. The greeting on return is a delayed in-process task started when the chat connects; promise follow-ups and nudges run in an in-process loop for users who are online. Typing dots go over realtime. |
| Reply failures | The user message is saved first. A failed reply shows "Not delivered · Retry"; fallback model on timeout. |
| Prompt | Friends-first v3 base prompt, standalone. v1 and v2 (dating era) moved to `_archive/agent/behavior_versions/`. |
| Prompt v4 (default) | Default since 2026-10-06 (v3-1 kept for rollback with `AGENT_BEHAVIOR_VERSION=v3-1`): Omi's character and a reply goal instead of stacked rules; context in tagged blocks (`<omi>`, `<rules>`, `<format>`, `<about_user>`, `<friend_vibe>`, `<memories>`, `<your_notes>`, `<this_chat>`, `<attached>`, `<this_turn>`, `<goal>`) with a size limit each and line breaks kept; code passes turn facts (message length, open question, Omi's last questions, reply requests from the last 3 messages) instead of the keyword plan. First smoke run on Mistral Small: v4 4/10, v3-1 3/10 (1 sample, self-judged, noisy); livelier but invents small stories, mixes gendered Hinglish forms and dodges direct opinions. Note: the character card (`AGENT_PERSONA_CARDS_ENABLED`) is off, so v3-1 runs with no character. |
| Models | Chat: Mistral Small 3.2 (Gemma 4 31B on trial; it led a 5-model chat test, report `reports/model-bench-2026-10-06.html`). Background memory: Qwen3 235B, set apart from the chat model (`MEMORY_BACKGROUND_V2_MODEL`); a changing-facts eval had it level with DeepSeek V3.2 at half the cost. Vibe proof check: DeepSeek V3.2. |
| Reply feedback | Rated replies (last 3 disliked, 2 liked, 30 days, with reasons) go into the `<how_to_talk>` block on the next reply. "No questions" / "just listen" requests start the background run at once. The chat has no 👍/👎 buttons yet. |
| Topics | Keyword topic picker removed. The active subject comes from the background model's threads; fresh angles on a low-energy turn come from the open vibe areas. |
| Threads | A thread needs a user message as proof. Code sets who started it from the message it began at. Only the user's own topics from the last 14 days come back in another chat. Deleting a chat deletes threads that lived only in it (the delete dialog lists them); orphans from older deletes are pruned on connect. An old topic is never offered while the user asked something or is answering Omi; the reply answers first. |
| Reply checks | A draft that uses a stock phrase (learned from chats plus a seed list), repeats an earlier reply, or asks too many questions gets one rewrite; extra questions are then trimmed. |

### Friend Vibe (the matching data)

The core of the product: what Omi understands about who the user would get along with.

- **11 areas.** Basics: what they want in a friend, humor, social energy, what they love, their days. Deeper: values and beliefs, stories that shaped them, differences they accept, deal-breakers, conflict, keeping in touch.
- **Written by the background model** as one or two plain English sentences per area, only from what the user said. Never from the companion's messages, never health, sexual or financial details, never dating preferences as friend preferences.
- **Proof on every line.** Each line cites the user messages behind it.
  1. Code checks each cited message is a real user message.
  2. A second model call (DeepSeek V3.2) sees each line with only its cited messages and keeps just the ones that really show it. Unproven lines are dropped; a failed check saves nothing.
- **Strength by days.** A line is Confirmed only when said on 2 or more different days; otherwise it is Still learning. The chip shows only that, colored by confidence (grey: one message, amber: several messages on one day, green: two days, solid green: three or more days). Tapping it lists the user's messages behind the line.
- **No proof, no line.** A rewritten line is re-proven with its old and new proof, and only proof that shows the new text stays. Deleting a chat removes its proof; a line left without proof goes and the milestone is recalculated. The delete dialog first says what goes with the chat (memories Omi forgets, vibe lines removed or weakened), and opening the Vibe page clears proof from chats deleted before this rule. `backfill_vibe_cards.py --recheck` re-proves existing cards once.
- **Milestones:** First impressions (any 2 lines) -> The basics -> Ready to match -> Deep. Every step after the first counts only solid lines.
- **In chat:** the companion gets the goal ("understand who they'd get along with, by being good company, never by interviewing"), what it knows, what is open and fresh milestone news. Never two areas in one reply, never right after a dodge, mood always first.
- **Backfill** for older chats: `scripts/backfill_vibe_cards.py` (dry run by default, `--apply`, `--force`, `--show`; skips eval and test accounts).

## 4. App (web) state

| Screen | State |
|---|---|
| Signup | One screen: name, approximate location ("Around Kolkata, West Bengal · Change", from the IP via DB-IP Lite, dropped when the browser timezone is in another country), 18+ checkbox. Everything else is learned in chat. |
| Chat | Omi with typing dots, bubble reveal, Retry on failed messages, "Talks like" setting, milestone note ("Omi knows what you want in friends · See your vibe"). New bubbles fade in; history does not. The typing dots leave in the same render the reply lands, and only one avatar shows while later bubbles reveal. A failed message shows a small "Not sent" with a retry icon. Typing state is per chat, and a reply never switches chats: it waits in its chat, and History marks chats with unseen messages (bold name and a dot, also on the phone History button). Seen counts live in the browser only; syncing them across devices needs a `last_read_count` column later. History rows: name and time, message count or typing dots, a "New" pill, a purple active row, and a ⋯ menu with Archive (or Unarchive) and Delete. Archived chats (`archived_at` column) sit in a collapsed "Archived (n)" group, keep their messages, get no greetings or nudges, and return to the main list when the user writes there. Switching chats highlights at once and reopens visited chats from memory. |
| Agent avatar | Generated "vibe blob" images, one per state (idle, thinking, listening, happy) as WebP in `apps/web/public/assets/agent/`. Still by default; only the one writing a reply breathes. No sweeps or flashes. |
| Vibe | Milestone path, each area's line with a chip (Still learning or Confirmed, colored by confidence). Tap the chip for the user's own messages, each with "Open in chat". "Not right" removes a line and it stays gone until the user says something new about that area. |
| Memories | Renamed from Style ("What Omiryn remembers"); `/style` redirects. Legacy signals hidden (data kept for export and deletion). Only current memories show; replaced or ended ones sit in a collapsed "Show old memories" section, greyed, with "Replaced by X on <date>" or "Ended on <date>". An "Omi isn't sure about" section lists open questions (Answer in chat / Not relevant). |
| Matches | Coming soon, plus how close the user is ("Matches need Ready to match") and a link to Vibe. |
| Profile | Personal profile card (what a match sees is a separate flow, decided with matching): photo inside a vibe ring (a blob shape seeded per person), name, age and place, an intro sentence and chips written by the model from non-private vibe lines (`GET /api/me/intro`, cached in the vibe card until those lines change, last intro kept if writing fails), photos, "Edit" for the intro and tags (saved as the user's own words, never overwritten, shown to the companion as how they describe themselves; "Let Omi rewrite" brings back an AI version guided by those words), "Not quite me" (opens Vibe) and "Edit details". The intro speaks to the user ("You ..."). Name and photo come from the profile everywhere, with Google's as the fallback. Below, "Account": email, gender, export, sign out, delete. One column, works on phones. Contact lives in the account menu. |

Navigation (branch `ui/contacts-layout`, not merged yet): web has a left rail with "Chats" (Omi, showing typing or its last line) and "You" (Vibe, Memories, Matches), and the account (Profile, Contact, Sign out) at the bottom. Phones get a top bar with icons, a contacts home, and a full-screen chat with no bottom bar. One ongoing chat with Omi (the newest chat not archived); older chats open read-only from the chat's ⋯ menu ("Earlier chats" drawer), with "Back to Omi". Usage (dev only) moved into the same menu and drawer. "Noted: ... · Not right?" lines appear under the reply where Omi learned a vibe line (once, at its newest proof). Memories, Vibe and Matches use one calm column (sentence-case labels, row menus, no technical tags); popups are restyled and become bottom sheets on phones.

### Landing site (`apps/landing`, port 5174)

Plain HTML with GSAP and ScrollTrigger, light theme. Fonts Geist, Geist Mono and Instrument Serif italic accents; brand gradient `#6d4aff` -> `#b04dd9` -> `#f062a8`. No college or dating wording anywhere.

| Section | State |
|---|---|
| Hero | Title, short subtext, button and one animation: two "vibe fingerprint" blobs with real portraits drift together and merge on shared traits. |
| How it works | Pinned scroll story: a phone chat where Omi picks up traits, then a match pops. |
| Vibe, reasons, match | Venn scrub, reasons marquee, draggable match card stack. |
| Early access | Lead form (intent "feedback") and final CTA. |
| Sub pages | About, How it works, Safety, AI disclosure, Privacy, Terms and Contact use the same look and nav. |

Portraits are 320 px WebP in `public/static/assets/people/`; source images stay in `design-assets/` (not deployed). Reduced motion gets a static page. The landing dev server has its own Vite cache (`node_modules/.vite-landing`) so it never breaks the web app's pre-bundled deps.

### UI next

Branch `ui/contacts-layout`, PR #2 (open): UI changes below are local and uncommitted, awaiting review. Test the full flow with a real account before merging. The previous PR checks used sample data.

| # | Item | Why |
|---|---|---|
| 1 | Signup and onboarding screens | Local visual refresh done; needs review and a new-account walkthrough. |
| 2 | Contact page | Local visual refresh and native radio controls done; needs review and submission check. |
| 3 | Milestone note above the composer | Local compact treatment done; needs a live milestone check. |
| 4 | Accessibility pass | Mobile navigation and focus styles improved locally; full keyboard and contrast audit still needed. |
| 5 | Phone extras | Local manifest, safe-area and visual-viewport work done; needs real iPhone keyboard and home-screen testing. |
| 6 | Mobile chat flow | Local change removes the one-chat screen; menu opens navigation. Needs review. |
| 7 | Consent for private areas | Values, stories and deal-breakers are marked private. Left: an explicit opt-in for using beliefs in matching (DPDP Act), and matching code that never shows these to the other user. |
| 8 | Vibe lines in "You ..." (agent team) | Lines are written in the third person ("They ..."), which reads cold on the user's own Vibe page. Belongs to the background prompt, not UI. |
| 9 | Profile loads every visit | Profile (and Privacy back to Profile) shows "Loading your profile" each time: the page remounts and refetches `/api/me/profile`, then `/api/me/data-requests` one after the other, though MainApp already fetched the profile. Fix: keep the last profile in memory, show it at once, refresh quietly in the background, and fetch both calls in parallel. There is no data cache anywhere except opened chats (Memories, Vibe and Matches refetch too), and profile photos are served `no-store`, so they re-download every visit; give photo URLs a version and cache them long. |

Done on the branch, after a UI review: phones open straight into the Omi chat; the chat header reads "Omi · Finds your people", with the name beside the back arrow on phones; a known vibe line said once shows "Said once" instead of "Still learning"; memories read as plain labels ("Study topic (current)") and one line per part instead of "likes: ... · favorite parts: ..."; Matches shows a clearly marked example introduction and three steps (talk with Omi, Omi finds someone, you both say yes).

Done before: shared loading, empty and error states (`StateView`) and notices (`Notice`); the design system across Chat, Vibe, Memories, Matches and Profile; a mobile pass on those screens; "Not right" stays gone; short neutral limit messages; optional profile gender.

## 5. Quality and checks

- Unit suite: about 950 backend tests and 28 web tests, independent of the developer `.env`.
- Memory evals with the real model: all 5 vibe grounding scenarios pass (small talk fills nothing, companion views never count, health and dating stay out, Hinglish filler fills nothing, only what the user showed).
- Companion vibe scenarios (no interviewing, a dodge is respected, mood first) are written but not yet run with the real model.

## 6. Next

After each deploy: set `AGENT_BEHAVIOR_VERSION=v4` and `MEMORY_BACKGROUND_V2_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507` in the prod env, check `GET /health` shows v4, then run `scripts/backfill_vibe_cards.py --recheck --apply` and `scripts/reprocess_memories.py --apply`.

Done: Reply quality (prompt v4, done); Memory recall eval (built); Attention (built); Dry-reply echo (done).

Next, in this order (set by the user 2026-10-08):

| # | Item | Why |
|---|---|---|
| 1 | Learning from feedback (backend done; 👍/👎 buttons in chat still to build) | 👍/👎 on replies is stored but never used: turn a 👎 into a "how to talk" memory with the reply as proof. Save "how to talk" requests right away instead of after the idle run. Add recall-test cases for requests and feedback. ("Keep it short" enforcement in code: left out for now, by choice.) |
| 2 | Learn from uploads | Today an uploaded text or WhatsApp export is stored raw: it reaches replies only when the message says words like "memory" or "about me", never becomes memories, vibe lines or the user card, and the upload section on the Memories page is commented out. Plan: store an upload as a hidden imported chat (real timestamps, only the user's own lines; they pick their sender in WhatsApp), so the existing background run turns it into memories, vibe and user card with proof, and deleting the upload deletes what it taught. Other people's lines are context, never facts about the user. Code measures their texting style (length, emoji, Hinglish mix, question rate) and the model writes a short style note into `<how_to_talk>`. Imported memories show "from your upload"; size cap keeps it a one-time few cents. Bring back the upload UI (Memories page or onboarding). Gives new users a running start. |
| 3 | Model choice in Profile | An "Advanced" setting in Profile to pick the chat model from the ones we offer. Each model gets 2-3 words on its strong point (for example "fun and chatty", "follows instructions", "most accurate"), so the user picks by feel, not by name. Small UI plus the existing model setting. |
| 4 | Current focus and consolidation | Things the user is into for a while ("studying transformers") are saved like lasting facts today, and even get the wrong kind (`procedural`, which means how to talk to them). Treat them like a human mind does: a "current focus" memory that stays fresh while mentioned, fades (kept, not deleted) after weeks of silence, and is later rolled up by consolidation into a broad lasting memory ("Studied machine learning in Sep-Oct 2026: transformers, attention"). The details stay searchable as history. Consolidation fits the daily reflection pass (item 7); threads stay for conversation subjects to continue. Freshness: each focus memory keeps its dates (created, last mentioned, valid from, valid until, archived). Freshness drops with time since it was last mentioned; past a point it is archived (not shown as current, still searchable). Only an explicit new mention refreshes it (last mentioned moves, archive lifts); code computes freshness from the dates, the model decides what counts as a mention. |
| 5 | Date-aware recall | "Today / this week" should fetch memories by date; support repeating events (birthdays, anniversaries, weekly gym). Code computes the dates. |
| 6 | Memory graph | Dots (people, things, events, feelings) and links with proof and time, in Postgres. Recall walks the links (like human association). Ideas from Zep/Graphiti and A-MEM. |
| 7 | Daily reflection | Once a day per user (runs on next visit): "how you are" traits with proof, "What Omi noticed" insights, open questions for curiosity. Ideas from Generative Agents and Letta sleep-time. |
| 8 | Deep matching | Match on patterns and chemistry between two people, not just shared interests. Our edge over interview-based apps (RealRoots, Known): weeks of real chat. |
| 9 | Friends-first memories | Memory rules and evals still treat partner preferences as matching data. |
| 10 | Embedding per vibe line | Lets matching shortlist people quickly. |
| 11 | Channels (one brain, many doors) | A channel gateway: each channel's webhook feeds the same `run_agent_turn`; one Omiryn identity linked per channel (one-time code or sign-in link), so memories, vibe and topics are shared; replies formatted per channel (bubbles become separate messages). Order: ChatGPT app (Apps SDK / MCP), then WhatsApp, then Telegram. WhatsApp: try it anyway with a test number on the Business Cloud API, framed as Omiryn's friend-matching service (matches, intros, meetup plans, reminders), then see how far chat can go. Risk: since 15 Jan 2026 Meta's Business API terms bar general-purpose AI assistants (ChatGPT and Perplexity left); Meta decides what counts as the main use, so the number could be cut off. Read Meta's current terms text first. Matching stays in the app. |

Dropped: the cross-chat "recent chats" note; the app now runs a single chat.

Open decision: memory evals grade purposes exactly, or only required-present / forbidden-absent.

## 7. Parked

- Voice input: test strong speech models on about 20 real Hinglish voice notes (Sarvam, OpenAI transcribe, ElevenLabs Scribe, Whisper large-v3 on DeepInfra) with an LLM cleanup step, then a built-in mic button. Keyboard dictation is too weak; Wispr Flow has no API. Later, a premium "Call Omi" voice mode that feeds the same memory and vibe pipeline.
- Meaning-based turn understanding, step 2: remove the keyword intent, emotion and stance rules and let the reply model read them. Run before-and-after evals first; Llama 3.3 may drift on requests made several turns back.
- VPN detection for the location estimate (DB-IP ASN file), and a "use my exact location" button.
- Human pairwise review of reply quality.
- A stronger reply model (DeepSeek V4 or Qwen 3.x are available on the account).

## 8. Not agent work (product)

- Friend compatibility check: compare two vibe cards.
- Matching: candidate pool, shortlist, both sides accept, introduction in chat.
- Match screens: match card (2 or 3 "you'd click on" reasons, one accepted difference), accept or pass, user-to-user chat with report and block, "still talking?" check at day 3 and 7.
- Vibe check by link (cold start): a friend opens a shared link, chats with Omi for about 2 minutes with no login, both get a shareable result card; sign-in is offered only after the result. The friend's chat is used for the score and then deleted.
- Omi as host: opens a new match chat with an icebreaker and leaves once the talk flows. No live score. Whether they keep talking after it leaves is the chemistry signal.
- Chat upload (backlog): WhatsApp "Export chat" file, parsed and cleaned in the browser (names, numbers, links removed), a recent sample processed in memory, text deleted, only the result kept. Few users are expected to upload, but the feature should exist. WhatsApp bots and APIs are ruled out (no access to personal chats; Meta's AI assistant policy).

## Related docs

- [production-plan.md](production-plan.md): the end-to-end launch list (core loop, growth, safety, privacy, infra, metrics) and the launch gate.
- [agent-roadmap.md](agent-roadmap.md): the phase plan for time, memory, persona and initiative.
- [friends-first-audit.md](friends-first-audit.md): where the old dating idea lived and how each piece moved.
- [agent-onboarding-plan.md](agent-onboarding-plan.md): first chat and new-user stages.
- [reply-quality-review-plan.md](reply-quality-review-plan.md): human review instead of AI taste judges.
- [architecture.md](architecture.md) and [api-contract.md](api-contract.md): system and API reference.
