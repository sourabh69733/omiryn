# Agent Testing Framework

Current priority: make companion behavior measurable before adding more behavior features.

## Implemented Now

- AI user model runs a live conversation with the companion.
- The same AI user judges whether the conversation felt worth continuing.
- An independent transcript judge reviews the full conversation separately.
- Consensus fails unless the AI user and independent judge both pass.
- Reports are written in simple Markdown plus full JSON under day-wise IST folders.
- Simulated scenarios can be listed and filtered by tags before running model calls.

## Scenario Matrix

Phase 3 starts small:

- User identity coverage: male and female Indian user scenarios.
- Language coverage: English and Hinglish scenarios.
- Scenario tags for discoverability: `backbone`, `india`, `english`, `hinglish`, `male`, `female`.

Later scenario categories:

- Hindi-only and regional Indian languages.
- Age, personality, attachment/communication style, and conversation pace.
- Memory, multi-session continuity, silence/follow-up, and re-initiation.
- Matchmaking advice, boundaries, privacy, safety, dependency risk, and manipulation.
- Long conversations, model comparisons, human review, and release gates.
