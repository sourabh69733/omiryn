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
- [src/matching/scorer.py](/Users/sourabh/nexus/work/p1/quack/omiryn/src/matching/scorer.py) - first deterministic matchmaking scorer

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

## Database

Drafts and agent conversations are persisted through SQLAlchemy.

Local default:

```bash
DATABASE_URL=sqlite:///./data/omiryn.db
```

Production target:

```bash
DATABASE_URL=postgresql+psycopg://user:password@host:5432/omiryn
```

Local Postgres service:

```bash
./scripts/db-up.sh
DATABASE_URL=postgresql+psycopg://omiryn:omiryn@localhost:5432/omiryn ./scripts/db-init.sh
DATABASE_URL=postgresql+psycopg://omiryn:omiryn@localhost:5432/omiryn ./scripts/db-check.sh
```

If your hosting provider gives a `postgres://...` or `postgresql://...` URL, the app
normalizes it to the installed `psycopg` driver automatically.

Reset local runtime data:

```bash
./scripts/reset-data.sh --yes
```

This creates a timestamped backup in `./backups` before clearing conversations,
imported context, drafts, and usage logs for the configured `DATABASE_URL`.
Use `--skip-backup` only when you are intentionally discarding disposable data.

Create a database backup without resetting:

```bash
./scripts/db-backup.sh
```

Tests default to `sqlite:///./data/omiryn_test.db`, and `reset_db()` refuses to
drop a non-test database unless `OMIRYN_ALLOW_RESET_DB=true` is set explicitly.

## Authentication

Omiryn is being prepared for Supabase Auth with Google OAuth.

Add these values to `.env` for local development:

```bash
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-public-anon-key
SUPABASE_JWT_AUDIENCE=authenticated

# Keep false while developing auth incrementally.
AUTH_REQUIRED=false
```

In Supabase, enable Google OAuth and add local redirect URLs:

```text
http://127.0.0.1:8000
http://localhost:8000
```

For deployment, also add the production app URL, for example:

```text
https://your-app.vercel.app
```

Do not commit Supabase service-role keys. The frontend should use only the
public anon key, and the API should verify user access tokens before user data
is scoped.

## Agent Providers

The app now supports the first Omiryn-owned agent flow:

```text
user chats with Omiryn agent -> extraction creates draft -> user reviews/approves
```

Provider options live in `.env`:

```bash
# no external model cost, good for development
AGENT_PROVIDER=mock

# hosted model
AGENT_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.1-8b-instant
GROQ_RPD_LIMIT=1000
GROQ_TPD_LIMIT=100000
GROQ_RPM_LIMIT=30
GROQ_TPM_LIMIT=6000

# hosted OpenAI-compatible model on DeepInfra
AGENT_PROVIDER=deepinfra
DEEPINFRA_API_KEY=...
DEEPINFRA_MODEL=meta-llama/Llama-3.3-70B-Instruct-Turbo

# hosted OpenAI-compatible model on Fireworks
AGENT_PROVIDER=fireworks
FIREWORKS_API_KEY=...
FIREWORKS_MODEL=accounts/fireworks/models/gpt-oss-120b

# local model
AGENT_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

For Ollama, start Ollama separately and pull a model first, for example:

```bash
ollama pull llama3.1
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

The agent package is grouped by responsibility so the context-engineered flow is easier to follow.

- `runtime/` - turn orchestration, provider calls, and usage request kinds.
- `context_engine/` - retrieval, context budgeting, prompt assembly, behavior/tone, and context snapshots.
- `memory_engine/` - durable profile facts, data-point extraction/review, user feedback, and WhatsApp-derived memory.
- `profile_engine/` - structured dating profile extraction and normalization.
- `evals/` - deterministic regression evals for fact capture and trace integrity.

Import new agent code from these grouped packages directly.
