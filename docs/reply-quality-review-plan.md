# Reply quality review plan

Written 25 September 2026. Parked for later; we are in the middle of other work.

## Why

Automated judges are good at facts (did it remember, is the date right) but weak at taste. They pass replies like "pizza nights are the best" that a real user finds boring. Reply quality has to be decided by people, and those decisions become the data that makes later evaluation trustworthy.

## Two kinds of testing

| Kind | Examples | How it is judged |
|---|---|---|
| Technical | Memory recall, corrections, dates and gaps, bubble count, leaked markers, stock phrases, question streaks, honesty about being an AI, retries and timeouts | Automated pass/fail, a gate for every change |
| Reply quality | Is it boring, specific, warm, fun, worth answering | Humans only; no automated pass/fail |

## Phases

### Phase 1: Collect replies to review
- Save every eval reply with its context (recent messages, time, prompt version, model).
- Optionally sample real chat replies, with consent and personal details removed.
- Store them as review items in the database.

### Phase 2: Review page
- One screen: the conversation so far, then two candidate replies side by side (for example old prompt vs new prompt).
- The reviewer picks the better one, or "both bad", with an optional short note ("boring", "too many questions", "felt fake").
- Pairwise picks are faster and more consistent than 1 to 4 scores.

### Phase 3: Reviewed dataset
- Every pick becomes a labeled example: context, reply A, reply B, winner, reasons.
- Track who reviewed and when; allow several reviewers per item to measure agreement.

### Phase 4: Use the data
- Compare prompt or model versions by human win rate on the same items.
- Calibrate AI judges against the human picks; use an AI judge only where it agrees with people.
- Build a gold set of good and bad replies for regression checks and, later, for examples or fine-tuning.

### Phase 5: Real usage signals
- Use in-app thumbs feedback, whether the user replies, reply length, and session length as outcome signals alongside human picks.

## Open questions
- Who reviews: only the team, or also trusted users?
- How many pairs per release before we trust a result?
- Privacy rules for using real chats in review.
