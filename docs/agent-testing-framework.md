# Agent Testing Framework V1

Purpose: make companion behavior measurable before changing the agent. Testing v1 is now the gate we use before agent-improvement work.

## Done

- AI user model runs a live conversation with the companion.
- The same AI user judges whether the conversation felt worth continuing.
- An independent transcript judge reviews the full conversation separately.
- Consensus fails unless the AI user and independent judge both pass.
- Reports are written in simple Markdown plus full JSON under day-wise IST folders.
- Simulated scenarios can be listed and filtered by tags before running model calls.
- Simulated scenarios can run as a tagged batch with one combined suite report.
- Full-conversation judges can be calibrated on known good/bad transcripts.
- Reports include improvement targets and a human-review placeholder.

## Core Commands

Calibrate the full-conversation judge:

```bash
python scripts/evals/run_simulated_conversation.py \
  --calibrate-conversation-judge \
  --user-provider deepinfra \
  --judge-provider openai \
  --judge-model gpt-4.1-mini
```

Run the testing v1 release gate:

```bash
python scripts/evals/run_simulated_conversation.py \
  --provider deepinfra \
  --prompt-version v3 \
  --user-provider deepinfra \
  --user-model deepseek-ai/DeepSeek-V4-Flash-0731 \
  --judge-provider openai \
  --judge-model gpt-4.1-mini \
  --scenario-tag core_v1
```

List current core scenarios:

```bash
python scripts/evals/run_simulated_conversation.py --list-scenarios --scenario-tag core_v1
```

## Current Core Scenarios

- User identity coverage: male and female Indian user scenarios.
- Language coverage: English and Hinglish scenarios.
- Scenario tags for discoverability: `backbone`, `india`, `english`, `hinglish`, `male`, `female`.
- Core v1 gate tag: `core_v1`.
- Release gate tag: `release_gate`.

Current core scenarios:

- `frustrated_user_tests_backbone`
- `frustrated_man_hinglish_tests_backbone`
- `frustrated_woman_english_tests_backbone`

## How To Use Reports

- Treat `PASS/FAIL` as the current automated verdict.
- Read `Improvement targets` first when a run fails.
- Use the target's `suggested_area` to decide which companion behavior module to inspect.
- Treat `Human review: pending` as a reminder that AI judge output is not final truth.
- After fixing the agent, rerun the same `core_v1` command and compare history.

## Pending Later Bucket

- Hindi-only and regional Indian languages.
- Age, personality, attachment/communication style, and conversation pace.
- Memory, multi-session continuity, silence/follow-up, and re-initiation.
- Matchmaking advice, boundaries, privacy, safety, dependency risk, and manipulation.
- Long conversations and larger model comparisons.
- Persistent human-review storage and judge-vs-human agreement tracking.
- Resume failed batch runs.
- Cost/time dashboard.
- Notion sync of verified summaries only.

## Next Product Step

Stop expanding testing v1 for now. Run the core gate, inspect improvement targets, and start improving the companion agent behavior from those failures.
