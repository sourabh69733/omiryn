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
| `POST /api/agent/conversations/{id}/messages` | Send a message. Optional `reply_to_index` quotes an earlier message. |
| `POST /api/agent/conversations/{id}/messages/deletion-impact` | `{"message_indexes": [...]}`: what deleting them also removes. |
| `POST /api/agent/conversations/{id}/messages/delete` | Delete those messages and what was learned only from them. |
| `DELETE /api/agent/conversations/{id}` | Delete a chat (also how the app ends a Temporary Chat). |
| `POST /api/agent/conversations/{id}/messages/{index}/feedback` | Rate one of Omi's replies: `good` or `bad` with `reasons` (`too_much`, `bad_tone`, `wrong_memory`, `not_helpful`). Replaces an earlier rating. Refused in Temporary Chat. |
| `DELETE /api/agent/conversations/{id}/messages/{index}/feedback` | Undo a rating. |
| `POST /api/me/omi/clear` | `{"confirm": "clear"}`: delete every chat and everything Omi learned; account and profile stay. |
| `DELETE /api/me/account-data?confirm=true` | Delete the account's private data. |
| `GET /api/admin/audit` | Admin only: audit rows, optional `user_id`. |
| `GET /api/agent/settings/model` | Reply models on offer (name, strong point), the default and the user's pick. |
| `PUT /api/agent/settings/model` | `{"model": "<id>"}` picks one; `{"model": null}` goes back to the default. |
| `GET /api/channels/telegram` | `available` (on for this account), `connected`, `bot_username`. |
| `POST /api/channels/telegram/link` | A `t.me` link with a one-time code (15 minutes); Start in Telegram connects. 404 when off, 403 when not on the tester list. |
| `DELETE /api/channels/telegram` | Disconnect; Omi says so in the Telegram chat. |
| `POST /api/channels/telegram/webhook` | Telegram only, checked by the `X-Telegram-Bot-Api-Secret-Token` header. Messages from a connected chat go to the user's Telegram chat with Omi (`channel: telegram`, hidden from the web list). |
| `POST /api/agent/conversations/{id}/whatsapp-import` | Upload a WhatsApp export (`content`, `user_sender`, `title`). With `style_kind: user_style`, Omi learns from the user's own lines through a hidden chat. |
| `POST /api/agent/conversations/{id}/context-sources` | Upload notes (`source_type: manual_notes` or `llm_profile`); Omi learns from them the same way. |
| `DELETE /api/me/context-sources/{source_id}` | Delete an upload and what Omi learned only from it. |
