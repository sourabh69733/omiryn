# Friends-first audit

Written 29 September 2026. Where the product still runs on the old dating idea, and how to move each piece to the locked direction:

> Omiryn: an AI you talk to that finds friends you'd actually get along with.

The AI is the doorway; the human match is the product. Vibe means who you can accept in your life (humor, beliefs on god, caste, politics and work, relatable stories, differences you tolerate), not similarity. Romance and dating are out of scope.

The public pages are already friends-first. The agent, onboarding and profile data are not: about 250 dating-era mentions across 48 files.

## 1. Live companion (prompt v3-1, pipeline v3): high priority

These shape every reply today.

| Piece | Where | Today | Friends-first |
|---|---|---|---|
| Companion chosen by who you date | `prompt_engine/modules/identity.py` (`agent_persona_for_interest`), `api/helpers.py` (`_agent_persona_for_profile`) | "Interested in women" gets Annie, "men" gets Kabir | One companion for everyone, AI-true (see open decision 1) |
| Conversation topics | `planning/topic_catalog.py` | Buckets such as partner attention, future partner, marriage, first crush, "safe intimacy" | Friend-vibe topics: humor, beliefs and values, relatable stories, how they spend free time, what they need from a friend, differences they can live with |
| Plan moves and boredom rescue | `planning/planner.py`, `modules/conversation_flow.py`, `versions/v2.py` | "safe_flirty_tease", "a sharper dating/personal angle", "playful/romantic angle" | Drop the flirt move; boredom rescue uses a sharper personal or opinion angle |
| Flirt and adult handling | `rules/intent.py` (`adult_flirty`), `policy/replies.py`, `modules/safety.py` | Flirty teasing allowed; "if unsure, stay romantic/flirty" | Friendly, never flirty. Keep 18+ rules and a clear boundary for sexual requests |
| Behavior block | `modules/behavior.py` | `dating_focus`, romantic-roleplay flag, "User basics: gender, interested_in", "not a dating interview" | Replace with a friend-matching focus; drop `interested_in` from the prompt |
| What the agent is quietly learning | `assembly/matching.py` (v3-1 only) | 5 basics: relationship intent, desired partner, preferred age, preferred location, partner personality. Deeper: attraction, family expectations, relationship dynamics... | Friend compatibility areas (proposal below) |
| Memory rules | `memories/taxonomy.py`, `memories/prompt.py`, `assembly/sources.py` | Examples use "partner preferences", "desired partner trait" | Examples about friends and compatibility |

Proposed friend compatibility areas, to replace the partner dimensions:

| Stage | Areas |
|---|---|
| Basics (learn first, naturally) | what they want from a friend; humor; social energy (quiet or loud, planned or spontaneous); where they are and when they are free; one or two interests that really matter to them |
| Deeper | beliefs and values (god, caste, politics, work); stories and experiences they relate to; differences they can accept; deal-breakers in a friend; how they handle conflict; how they keep in touch |

## 2. Onboarding and profile data: high priority

| Piece | Where | Today | Friends-first |
|---|---|---|---|
| Setup wizard | `apps/web/src/ui/onboarding/ProfileSetupWizard.tsx` | Step "Matching preferences: who and where you would like to meet", with Women / Men / Everyone | Ask where they are and what they are looking for in friends; see open decision 2 for gender |
| Profile page | `apps/web/src/ui/app/pages/ProfilePage.tsx` | "Interested in" select | Remove or replace to match the wizard |
| API | `api/routes/profile.py` (`/api/me/dating-basics`), `api/models.py` (`InterestedIn`) | Setup is "complete" only with `interested_in` | Rename to `/api/me/basics` (keep the old path as an alias for a release); drop the requirement |
| Stored data | `agent_user_profiles.interested_in` | Required field | Keep the column for existing users; stop using it for the persona and matching |
| Styling | `legacy-app.css` | `dating-basics-screen` class (59 uses) | Rename with the wizard; cosmetic |

## 3. First message and profile drafts: medium priority

| Piece | Where | Today | Friends-first |
|---|---|---|---|
| First message | `api/helpers.py` (`_initial_agent_message`) | "Hey {name}, I'm {Annie/Kabir}." | Part of Phase 5 in `agent-onboarding-plan.md`: honest intro as an AI that finds friends you'd get along with |
| Profile drafts | `outputs/profile_draft/` (`ExtractedDatingProfile`, "Extract a structured dating profile"), `api/routes/drafts.py`, admin "approved profiles" | A dating profile built from chats | A friend profile: the compatibility areas above plus a short "about me" |
| Onboarding plan | `docs/agent-onboarding-plan.md` | Built around the 5 dating basics | Rewrite around the friend basics above |

## 4. Legacy pipelines v1 and v2: low priority, but check production

| Piece | Where | Today |
|---|---|---|
| v1 prompt | `versions/v1.py` | "You are Omiryn's private dating companion", partner preferences, flirty rules |
| v2 data points | `memory_engine/data_points/extraction/` (prompts, legacy rules, WhatsApp rules) | Partner-preference extraction |

Recommendation: delete v1 and the v2 data-point pipeline instead of rewriting them; v3 is what runs. Update (2 October): the code and deploy scripts now default to v3, and v1 and v2 prompts are archived; `GET /health` shows what a deploy runs.

## 5. Evals and docs: medium priority

| Piece | Where | Today |
|---|---|---|
| Behavior scenarios | `evals/behavior/core/scenarios.py` (5 dating mentions), `scenarios_v2.py` ("first date: coffee or a long walk?") | Dating situations |
| Memory scenarios | `evals/memory/v3/scenarios.py` (16 mentions) | Partner preferences as expected memories |
| Docs | `docs/architecture.md`, `docs/mvp-roadmap.md`, `docs/omiryn-agent-handoff.md` | "Matchmaker" and dating framing |

Evals must change with the prompts, or they will fail the new behavior (or pass the old one).

## Open decisions

1. **Companion persona.** Annie and Kabir exist because a dating user picked a gender. For friends: one companion for everyone (recommended, and matches the AI-true persona plan), or let the user pick a name and style?
2. **Gender in friend matching.** Drop "interested in" entirely, or keep an optional "prefer friends of my gender" (some people, often women, want this at first for comfort)? Recommended: optional, off by default, never required.
3. **Legacy v1 and v2.** Delete (recommended) or keep and rewrite?
4. **Flirting.** Remove the flirt mode entirely (recommended for friends-first), keeping only a polite boundary for sexual requests.

## Suggested order

1. Confirm the production pipeline version, and decide the four open questions.
2. Live companion: persona, topics, planner moves, flirt handling, behavior block. Update the evals in the same change.
3. Friend compatibility areas in `matching.py` and the memory rules.
4. Onboarding, profile page and API rename.
5. Profile drafts, first message and the onboarding plan (Phase 5).
6. Delete the legacy pipelines; refresh the docs.
