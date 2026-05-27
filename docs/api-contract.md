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
