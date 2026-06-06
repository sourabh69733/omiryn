# Omiryn

Omiryn is an AI-assisted matchmaking platform. Users chat with an onboarding
agent, the system converts those conversations into structured relationship
data, and matches are suggested with clear compatibility explanations.

The product direction is intentionally not "AI pretends to be the user." AI is
used to understand users, curate matches, and coach conversations while human
users remain in control.

## First MVP

1. User creates a basic dating profile.
2. User completes an AI onboarding conversation.
3. The conversation is extracted into a structured dating profile.
4. The matchmaking engine suggests a small number of compatible users.
5. Both users approve before a human-to-human chat opens.
6. Users give feedback so future suggestions improve.

## Repository Structure

- [docs/architecture.md](/Users/sourabh/nexus/work/p1/quack/omiryn/docs/architecture.md) - system architecture and service boundaries
- [docs/mvp-roadmap.md](/Users/sourabh/nexus/work/p1/quack/omiryn/docs/mvp-roadmap.md) - staged product build plan
- [db/schema.sql](/Users/sourabh/nexus/work/p1/quack/omiryn/db/schema.sql) - initial relational data model
- [docs/api-contract.md](/Users/sourabh/nexus/work/p1/quack/omiryn/docs/api-contract.md) - first API surface
- [llm/profile-extraction.schema.json](/Users/sourabh/nexus/work/p1/quack/omiryn/llm/profile-extraction.schema.json) - structured output schema for dating profile extraction
- [llm/onboarding-agent.md](/Users/sourabh/nexus/work/p1/quack/omiryn/llm/onboarding-agent.md) - onboarding agent behavior
- [src/omiryn/matching/scorer.py](/Users/sourabh/nexus/work/p1/quack/omiryn/src/omiryn/matching/scorer.py) - first deterministic matchmaking scorer

## Python Setup

```bash
./scripts/setup.sh
```

Use `.env` for local secrets and machine-specific config. Keep `.env.example`
updated whenever a new required setting is added.

## Run App

```bash
./scripts/start.sh
```

For auto-reload during development:

```bash
APP_RELOAD=true ./scripts/start.sh
```

Then open:

- App UI: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`
- Docs: `http://127.0.0.1:8000/docs`

## Agent Submission Flow

The first agent-integration path is draft-first:

1. An external agent submits a relationship profile to
   `POST /api/agent-submissions/profile`.
2. Omiryn creates a draft and returns a review URL.
3. The user reviews, edits, approves, or deletes the draft.
4. Only approved drafts should enter matching.

The ChatGPT Action starter spec lives at
[docs/chatgpt-action-openapi.yaml](/Users/sourabh/nexus/work/p1/quack/omiryn/docs/chatgpt-action-openapi.yaml).

## Product Principle

Less swiping, better understanding, more intentional introductions.
