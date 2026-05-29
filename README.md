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
python -m venv .venv
source .venv/bin/activate
cp .env.example .env
pip install -r requirements.txt
pip install -e .
python -m unittest discover -s tests
```

Use `.env` for local secrets and machine-specific config. Keep `.env.example`
updated whenever a new required setting is added.

## Run App

```bash
source .venv/bin/activate
./scripts/start.sh
```

Then open:

- API: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`
- Docs: `http://127.0.0.1:8000/docs`

## Product Principle

Less swiping, better understanding, more intentional introductions.
