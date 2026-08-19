CREATE TABLE feedback_submissions_v3 (
  response_id TEXT PRIMARY KEY,
  survey_version TEXT NOT NULL,
  client_token_hash TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  dating_openness TEXT NOT NULL,
  compatibility_challenges TEXT NOT NULL,
  compatibility_signals TEXT NOT NULL,
  ai_disclosure_comfort TEXT NOT NULL,
  depth_vs_speed TEXT NOT NULL,
  intro_time_willingness TEXT NOT NULL,
  concept_concerns TEXT NOT NULL,
  must_get_right TEXT NOT NULL DEFAULT ''
);

-- Earlier respondents were not shown the two new AI-preference questions.
-- Preserve their rows with explicit labels instead of inferring answers.
INSERT INTO feedback_submissions_v3 (
  response_id,
  survey_version,
  client_token_hash,
  source_hash,
  received_at,
  dating_openness,
  compatibility_challenges,
  compatibility_signals,
  ai_disclosure_comfort,
  depth_vs_speed,
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
  dating_openness,
  compatibility_challenges,
  compatibility_signals,
  'Legacy response - not asked',
  'Legacy response - not asked',
  intro_time_willingness,
  concept_concerns,
  must_get_right
FROM feedback_submissions;

DROP TABLE feedback_submissions;
ALTER TABLE feedback_submissions_v3 RENAME TO feedback_submissions;

CREATE UNIQUE INDEX ux_feedback_submissions_version_client
  ON feedback_submissions (survey_version, client_token_hash);

CREATE INDEX ix_feedback_submissions_source_received
  ON feedback_submissions (source_hash, received_at);
