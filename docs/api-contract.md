# Initial API Contract

This is the first backend surface for the MVP. It is intentionally small.

## Auth

### `POST /auth/start`

Starts login or signup.

```json
{
  "channel": "phone",
  "identifier": "+919999999999"
}
```

### `POST /auth/verify`

Verifies OTP and returns a session.

```json
{
  "identifier": "+919999999999",
  "otp": "123456"
}
```

## Profiles

### `GET /me`

Returns the current user, basic profile, and structured profile status.

### `PATCH /me/profile`

Updates basic profile fields.

```json
{
  "displayName": "Aarav",
  "dateOfBirth": "1997-04-12",
  "gender": "man",
  "city": "Bengaluru",
  "relationshipIntent": "long_term"
}
```

## Agent Onboarding

### `POST /agent/conversations`

Creates an onboarding conversation.

```json
{
  "type": "onboarding"
}
```

### `POST /agent/conversations/{conversationId}/messages`

Adds a user message and returns the agent response.

```json
{
  "message": "I want something serious, but I need time to trust someone."
}
```

### `POST /agent/conversations/{conversationId}/extract`

Starts structured profile extraction from the transcript.

## Matches

### `GET /matches/suggestions`

Returns curated match suggestions.

### `POST /matches/{matchId}/decision`

Accepts or rejects a suggested match.

```json
{
  "decision": "accept",
  "reason": "Looks compatible"
}
```

## Human Chat

### `GET /chats`

Returns active chats unlocked by mutual match approval.

### `POST /chats/{chatId}/messages`

Sends a human-authored message.

```json
{
  "message": "Hey, I liked that we both care about slow travel."
}
```

## Feedback

### `POST /matches/{matchId}/feedback`

Collects match quality feedback.

```json
{
  "rating": 4,
  "outcome": "good_chat",
  "notes": "Conversation felt natural, but lifestyle may differ."
}
```

## Chat And Privacy Routes (built, October 2026)

The sections above are the first sketch. These routes exist in `src/api/routes` today:

| Route | What it does |
| --- | --- |
| `POST /api/agent/conversations` | Start a chat. `{"temporary": true}` starts a Temporary Chat (never in History, never learned from). |
| `POST /api/agent/conversations/{id}/messages` | Send a message, also while Omi is replying. Optional `reply_to_index` quotes an earlier message; optional `client_id` (up to 64 chars) matches the app's pending bubble and stops a retried send being saved twice. The request that starts a burst stays open and returns the replies; one that joins a burst returns once saved, with the message at `delivery_status: sending`, and its reply arrives on the first request and over realtime. Omi may answer with no new message: the user's message then carries `reaction` (one emoji, also sent on `message.created`) or `no_reply: true`. |
| `POST /api/agent/conversations/{id}/typing` | HTTP backup for the realtime command `{"type": "typing", "scope": "conversation", "scope_id": id, "active": true}`, which a subscribed socket sends about once a second while a reply is pending and which gets no answer. `active: false` means the box was cleared. No effect when nothing is pending. |
| Message `card` (to build, server side) | While hosting a match, one of Omi's messages may carry `card`: `{"kind": "match_ask" \| "match_plan" \| "match_consent" \| "match_checkin", "pair_id", "title"?, "headline"?, "detail"?, "lines"?: [..], "note"?, "actions": [{"id", "label", "reply", "primary"?}], "answered"?: "<action id>"}`. Omi's words stay in `content`; the card holds the facts code gave it (the plan, the number line, the chips). The app renders it under the bubble (`MessageCard`) and shows "You said: <label>" once `answered` is set. Also sent on `message.created`. |
| `POST /api/me/matches/{pair_id}/report` (to build) | `{"reason": "uncomfortable" \| "not_who_they_said" \| "spam" \| "other", "note"?, "block": true}`. Records the report for the team, declines the pair, and with `block` keeps the two out of each other's future candidates (the filter in docs/matching-design.md 3.2). Returns the card with status `blocked` (or `declined` without block). The other person is told nothing beyond "not this week" or that the meet won't happen. |
| Card field `number_shared` (to build) | On `GET /api/me/matches` cards: `true` once both people shared their number through Omi (the `match_consent` card or words). The app only shows "numbers shared" on the person's row; sharing itself and "stop" stay in the chat. |
| Send with `card_action` (to build, server side) | `POST .../messages` may add `card_action: {"message_index", "pair_id", "action"}` when the user tapped a card: the `message` is that action's `reply` text, so the host reads words exactly as on WhatsApp; the server sets `answered` on that message's card and treats a tap on a `match_ask` card like `POST /api/me/matches/{pair_id}/answer`. |
| `POST /api/agent/conversations/{id}/messages/deletion-impact` | `{"message_indexes": [...]}`: what deleting them also removes. |
| `POST /api/agent/conversations/{id}/messages/delete` | Delete those messages and what was learned only from them. |
| `DELETE /api/agent/conversations/{id}` | Delete a chat (also how the app ends a Temporary Chat). |
| `PUT /api/agent/conversations/{id}/messages/{index}/reaction` | The user's emoji on one of Omi's messages: `{"emoji": "😂"}`, one emoji, replacing an earlier one. Saved as `user_reaction`, sent to other tabs as `message.user_reaction`. Does not start a reply. 404 on a user's or deleted message, 422 when it is not one emoji. |
| `DELETE /api/agent/conversations/{id}/messages/{index}/reaction` | Take the reaction back. |
| `POST /api/agent/conversations/{id}/messages/{index}/feedback` | Rate one of Omi's replies: `good` or `bad` with `reasons` (`too_much`, `bad_tone`, `wrong_memory`, `not_helpful`). Replaces an earlier rating. Refused in Temporary Chat. |
| `DELETE /api/agent/conversations/{id}/messages/{index}/feedback` | Undo a rating. |
| `GET /api/me/memories` | Each memory also has `repeats`: `yearly:03-12`, `monthly:5`, `weekly:tue,thu`, or null when it does not repeat; and `about`: the names it is about, used to link memories. |
| `POST /api/me/omi/clear` | `{"confirm": "clear"}`: delete every chat and everything Omi learned; account and profile stay. |
| `DELETE /api/me/account-data?confirm=true` | Delete the account's private data. |
| `GET /api/admin/audit` | Admin only: audit rows, optional `user_id`. |
| `GET /api/admin/dashboard?days=14` | Admin only: `kpis` (active today/7d/previous 7d, returning, new users, replies and failed replies, cost today/7d/30d, messages), `daily` (active users, replies, failed, cost, new users per UTC day), `omi` (prompt version, reply model, p50/p95 reply latency, ratings, last error), `health` (memories, jobs, batch failures, open data requests, channels), `recent_users`, `attention` (level, title, detail, route, count). No chat or memory text. |
| `GET /api/admin/people` | Admin only: every user with name, place, joined, last active, replies (total, 7d, failed), spend, chats, memories, profile facts, linked channels. |
| `GET /api/admin/people/{user_id}` | Admin only, audited as `admin.view_user`: profile basics, settings, linked channels, matching, chats (metadata, replies and spend per chat), memory counts by kind, usage with 30 daily points and ratings, and the admin access log for this user. 404 when unknown. |
| `GET /api/admin/costs?days=30` | Admin only: totals, daily calls/failures/tokens/cost/replies, `by_kind`, `by_model`, `reply_latency` (p50, p90, p95, max), `recent_failures`, `recent_calls`. |
| `GET /api/admin/system` | Admin only: runtime flags, jobs by kind and status with failing jobs, memory pipeline counts and failing batches, channel links, eval runs, the latest 30 audit rows. |
| `GET/POST /api/admin/pools` | Admin only: match pools (name, join code, match weekday). |
| `GET /api/admin/pools/{id}` | Admin only: the pool's members with readiness and non-private vibe lines, pairs so far, suggested pairs. |
| `POST /api/admin/pools/{id}/pairs` | Admin only: `{"user_a","user_b"}`; runs the compatibility check, stores the pair as `proposed`. |
| `POST /api/admin/pairs/{id}/introduce` | Admin only: `{"place"?, "when"?, "meet_at"?}` (`meet_at` ISO 8601 with offset). Marks the pair `introduced`, queues Omi's introduction to both in their own chats, a reminder before the meet and check-ins at day 3 and day 30. 409 when the pair is not `proposed`. |
| `PATCH /api/admin/pairs/{id}` | Admin only: `{"status"}`, one of candidate, proposed, asked, introduced, met, no_show, declined, expired, still_talking. |
| `POST /api/admin/pools/{id}/pick` | Admin only: match day. Judges the pairs that need it, stores them as candidates, and returns `{pairs, group, waiting, busy, dropped, judged}`; the picked pairs become proposed. Nothing reaches a user. |
| `POST /api/admin/pairs/{id}/ask` | Admin only: Omi tells both people about each other (first name, reasons, difference) and asks whether to introduce them; 48 hours to answer. 409 unless the pair is proposed. |
| `GET /api/me/matches` | The user's match cards: `{pair_id, status, name, reasons[{area,text}], difference, icebreaker, plan{place,when}|null, asked_at, answer_by, introduced_at}`. `status`: asked (waiting for you), waiting (you said hi), introduced, met, still_talking, declined, no_show, expired. Only pairs the user has heard about; never the other person's notes or a score. |
| `POST /api/me/matches/{id}/answer` | `{"answer": "accept"|"pass"}`. Both accept: introduced and Omi introduces them in chat. A pass closes it; the other person hears only "not this week". 404 unknown pair, 409 when no longer open. |
| `GET /api/me/pools`, `POST /api/me/pools/join`, `DELETE /api/me/pools/{id}` | The user's pools and pair statuses (never the reasons), join by code, leave. |
| `GET /api/me/match-readiness` | Whether the user can be matched yet and what is missing, in plain blockers. |
| `GET /api/agent/settings/model` | Reply models on offer (name, strong point), the default and the user's pick. |
| `PUT /api/agent/settings/model` | `{"model": "<id>"}` picks one; `{"model": null}` goes back to the default. |
| `GET /api/channels/telegram` | `available` (on for this account), `connected`, `bot_username`. |
| `POST /api/channels/telegram/link` | A `t.me` link with a one-time code (15 minutes); Start in Telegram connects. 404 when off, 403 when not on the tester list. |
| `DELETE /api/channels/telegram` | Disconnect; Omi says so in the Telegram chat. |
| `GET /api/channels/whatsapp` | `available`, `connected`. |
| `POST /api/channels/whatsapp/link` | A `wa.me` link with "connect <one-time code>" typed in (15 minutes). 404 when off, 403 when not on the tester list. |
| `DELETE /api/channels/whatsapp` | Disconnect; Omi says so in the WhatsApp chat. |
| `GET /api/channels/whatsapp/webhook` | Meta's webhook verification (`hub.verify_token`, echoes `hub.challenge`). |
| `POST /api/channels/whatsapp/webhook` | Meta only, checked by `X-Hub-Signature-256`. Answers 200 at once; messages from a connected number go to the user's WhatsApp chat with Omi. |
| `POST /api/channels/telegram/webhook` | Telegram only, checked by the `X-Telegram-Bot-Api-Secret-Token` header. Messages from a connected chat go to the user's Telegram chat with Omi (`channel: telegram`, hidden from the web list). |
| `POST /api/agent/conversations/{id}/whatsapp-import` | Upload a WhatsApp export (`content`, `user_sender`, `title`). With `style_kind: user_style`, Omi learns from the user's own lines through a hidden chat. |
| `POST /api/agent/conversations/{id}/context-sources` | Upload notes (`source_type: manual_notes` or `llm_profile`); Omi learns from them the same way. |
| `DELETE /api/me/context-sources/{source_id}` | Delete an upload and what Omi learned only from it. |
| `GET /api/me/profile` uploads (`memory_sources`, `style_sources`) | Each read upload also has `digest`: `summary`, `chat_dates`, `topics` (title, started, ended). No quoted lines. |
| `GET /api/me/context-sources/{source_id}/reading` | How far Omi got reading an upload: `state` (`queued`, `reading`, `merging`, `done`, `failed`, or `none` for older uploads), `parts`, `parts_done`, `learned`, `seconds`. The same object is in the upload's `metadata.reading`. |
| `GET /api/me/consent` | Whether matching may use the private vibe areas (values, stories, deal-breakers): `private_matching`, `asked` (false means never asked, which counts as no), `at`. Also returned as `consent` in `GET /api/me/vibe`. |
| `PUT /api/me/consent` | `{"private_matching": true|false}`: allow or stop it; takes effect at once. Stored as `_consent` on the vibe card. Matching must check `storage.private_matching_allowed(card)` before using a private area, and never shows or quotes one to the other user. |
