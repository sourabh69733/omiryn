# Omiryn production plan

Last updated 2 October 2026. What Omiryn needs to run end to end as a real product, and where each piece stands. [progress.md](progress.md) is the map of the agent and app; this page is the launch list.

Security and infra details live in [production-security-checklist.md](production-security-checklist.md) and [gcp-deployment.md](gcp-deployment.md); this page links to them instead of repeating them. [mvp-roadmap.md](mvp-roadmap.md) is from the dating era and is replaced by this page.

Status: **Done**, **Partial**, **Missing**.

## 1. Core loop

The product works only when all eight steps work for two real users.

| # | Step | Status | What is left | Done when |
|---|---|---|---|---|
| 1 | Signup | Done | Nothing for launch. | A new user reaches Omi's first message in under 60 s; 18+ cannot be skipped. |
| 2 | Talk to Omi | Partial | Make pipeline v3 the default (code, `.env.example`, deploy scripts, Cloud Run); friends-first memories. | Testers chat 10+ minutes on their own; replies never read like a template. |
| 3 | Vibe extraction | Done | Backfill `--reset`; embedding per vibe line for matching. | Grounding evals pass with the real model; every line has proof. |
| 4 | Vibe page | Partial | A removed line can come back (store the rejection, accept only newer proof); sensitive areas marked "matching only". | The user removes a wrong line and it stays gone until new proof. |
| 5 | Matching | Missing | Candidate pool (city, age band, recently active), minimum vibe ("Ready to match"), pair score (humor fit, values same or accepted, deal-breaker clashes, interests, energy), AI-written reasons. | Real friend pairs score higher than random pairs; reasons read true to both people. |
| 6 | Match flow | Missing | Match card (first name, photo if given, 2 or 3 "you'd click on" reasons, one accepted difference), accept or pass, chat opens only on both accepting, a few matches a day, expiry. | Two test users get matched, both accept, the chat opens for both. |
| 7 | User-to-user chat | Missing | Realtime 1:1 chat (reuse the Omi realtime layer), Omi icebreaker, notifications, report and block. | Two users chat on phones, get notified, and can block each other. |
| 8 | Feedback loop | Missing | "Still talking?" at day 3 and 7; automatic day-7 still-talking signal; outcomes fed back into matching. | The 7-day still-talking rate shows on a dashboard. |

## 2. Growth and cold start

| Item | Status | Notes |
|---|---|---|
| Landing site and early access form | Done | `apps/landing`; lead form stores intent "feedback". |
| Vibe check by link | Missing | A friend opens a link, chats with Omi about 2 minutes with no login, both get a result card. Sign-in only after the result. The friend's chat is used for the score and then deleted. |
| Shareable result card | Missing | Image for WhatsApp and Instagram. |
| Omi as host in match chats | Missing | Icebreaker, then leaves once the talk flows. Part of step 7. |
| Chat upload | Partial | A server-side WhatsApp export parser already exists (`src/ingestion/whatsapp.py`, speaking-style import). For a vibe check it needs: in-browser cleaning (names, numbers, links), in-memory processing, text deleted, only the result kept. Low expected use; build after the core loop. |

## 3. Safety

| Item | Status | Notes |
|---|---|---|
| Adults only | Done | 18+ at signup. |
| Rate limits and AI quotas | Done | Durable per-user quotas and burst protection. |
| Report and block | Missing | Required on every match card and user-to-user chat. |
| Message moderation | Missing | Abuse, sexual content, scams and contact-sharing pressure in user-to-user chat. |
| Crisis replies | Missing | Self-harm and danger signals get a safe reply and helpline information. |
| Fake and duplicate accounts | Missing | One account per person, basic checks before matching. |
| Safety alerts | Missing | Alerts for repeated reports and throttling (also in the security checklist). |

## 4. Privacy and legal

| Item | Status | Notes |
|---|---|---|
| Privacy, Terms, Safety, AI disclosure, Contact pages | Done | Copy should be re-read against the friends-first product before launch. |
| Delete account and data | Done | Covers profile, chats, memories, photos, signals, logs. |
| Data export | Partial | Requests are stored; the export file itself is not generated. |
| Consent for sensitive vibe data (DPDP Act) | Missing | Values and beliefs are used for matching only with clear consent, never shown to matches. |
| AI provider data terms | Missing | Confirm DeepInfra and the vibe check model do not store or train on API data, and say so on the Privacy page. |
| Branded support email, legal review | Missing | From the security checklist. |

## 5. Infra and ops

See [gcp-deployment.md](gcp-deployment.md) and the security checklist for the full list.

| Item | Status | Notes |
|---|---|---|
| Cloud Run, Postgres, GCS photos, secrets | Partial | Terraform and scripts exist; production `DATABASE_URL` and Supabase production redirects are not confirmed. |
| Backups and a tested restore | Missing | |
| Pipeline v3 in production | Missing | Deploy scripts still default to v2. |
| Realtime across instances | Missing | Redis Pub/Sub before running more than one instance. |
| Error and cost monitoring | Partial | Client errors and request IDs exist; no alerts for chat failures, provider rate limits or spend. |
| Model fallback | Done | Llama 3.1 70B after a 25 s timeout. |
| CI and one-step deploy | Missing | Tests and build on every push. |

## 6. Metrics

| Metric | Status | Notes |
|---|---|---|
| Activation (first real chat with Omi) | Partial | App events exist; the definition and dashboard do not. |
| Match rate (both accept) | Missing | Needs step 6. |
| 7-day still-talking rate | Missing | Needs steps 7 and 8. The main success number. |
| Dashboard for the three numbers | Missing | Admin app is the natural place. |

## 7. UI polish

Tracked in [progress.md](progress.md) under "UI next": one design system for app and landing, profile cleanup, chat header, limit messages, mobile pass, empty and error states.

## Launch gate (first 50 users)

Ship when all of these are done; everything else can follow.

- [x] Signup with 18+ (step 1)
- [ ] Pipeline v3 is the default everywhere (step 2)
- [x] Vibe extraction with proof (step 3)
- [ ] Vibe page: removed lines stay removed; sensitive areas private (step 4)
- [ ] Matching, match flow and user-to-user chat (steps 5 to 7)
- [ ] Day-3 and day-7 check and the still-talking signal (step 8)
- [ ] Report, block, moderation and crisis replies
- [ ] Delete account works in production; AI provider data terms confirmed
- [ ] Production hosting, backups, error and spend alerts
- [ ] Activation, match rate and 7-day still-talking events recorded
- [ ] Sign-in, chat, vibe, match and delete flows tested by hand on a phone
