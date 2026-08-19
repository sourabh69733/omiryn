CREATE TABLE feedback_submissions_v2 (
  response_id TEXT PRIMARY KEY,
  survey_version TEXT NOT NULL,
  client_token_hash TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  dating_openness TEXT NOT NULL,
  compatibility_challenges TEXT NOT NULL,
  compatibility_signals TEXT NOT NULL,
  likelihood_to_try TEXT NOT NULL,
  intro_time_willingness TEXT NOT NULL,
  concept_concerns TEXT NOT NULL,
  must_get_right TEXT NOT NULL DEFAULT ''
);

-- Preserve any early v1 responses if the first migration reached production.
-- Legacy labels remain visible during analysis instead of inventing answers to
-- questions those respondents were never shown.
INSERT INTO feedback_submissions_v2 (
  response_id,
  survey_version,
  client_token_hash,
  source_hash,
  received_at,
  dating_openness,
  compatibility_challenges,
  compatibility_signals,
  likelihood_to_try,
  intro_time_willingness,
  concept_concerns,
  must_get_right
)
SELECT
  response_id,
  survey_version,
  client_token_hash,
  source_hash,
  received_at,
  'Legacy response - not asked',
  compatibility_challenges,
  compatibility_signals,
  concept_usefulness,
  'Legacy response - not asked',
  concept_concerns,
  must_get_right
FROM feedback_submissions;

DROP TABLE feedback_submissions;
ALTER TABLE feedback_submissions_v2 RENAME TO feedback_submissions;

CREATE UNIQUE INDEX ux_feedback_submissions_version_client
  ON feedback_submissions (survey_version, client_token_hash);

CREATE INDEX ix_feedback_submissions_source_received
  ON feedback_submissions (source_hash, received_at);
