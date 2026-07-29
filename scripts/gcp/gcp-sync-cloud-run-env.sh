#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_SERVICE
require_var DATABASE_URL_SECRET
require_var ENCRYPTION_MASTER_KEY_SECRET
require_var DEEPINFRA_API_KEY

gcloud config set project "$GCP_PROJECT_ID"

secret_args=(
  "$(optional_secret_arg DATABASE_URL "$DATABASE_URL_SECRET")"
  "$(optional_secret_arg ENCRYPTION_MASTER_KEY "$ENCRYPTION_MASTER_KEY_SECRET")"
  "$(optional_secret_arg SUPABASE_URL "${SUPABASE_URL_SECRET:-}")"
  "$(optional_secret_arg SUPABASE_ANON_KEY "${SUPABASE_ANON_KEY_SECRET:-}")"
  "$(optional_secret_arg SECRET_KEY "${SECRET_KEY_SECRET:-}")"
  "$(optional_secret_arg GROQ_API_KEY "${GROQ_API_KEY_SECRET:-}")"
  # "$(optional_secret_arg DEEPINFRA_API_KEY "${DEEPINFRA_API_KEY_SECRET:-}")"
  "$(optional_secret_arg FIREWORKS_API_KEY "${FIREWORKS_API_KEY_SECRET:-}")"
  "$(optional_secret_arg OPENAI_API_KEY "${OPENAI_API_KEY_SECRET:-}")"
)

filtered_secret_args=()
for value in "${secret_args[@]}"; do
  if [ -n "$value" ]; then
    filtered_secret_args+=("$value")
  fi
done

env_vars=(
  "APP_ENV=${APP_ENV:-production}"
  "AUTH_PROVIDER=${AUTH_PROVIDER:-supabase}"
  "AUTH_REQUIRED=${AUTH_REQUIRED:-true}"
  "SUPABASE_JWT_AUDIENCE=${SUPABASE_JWT_AUDIENCE:-authenticated}"
  "DB_DISABLE_POOL=${DB_DISABLE_POOL:-true}"
  "AGENT_PROVIDER=${AGENT_PROVIDER:-mock}"
  "PROFILE_DEBUG_DATA_ENABLED=${PROFILE_DEBUG_DATA_ENABLED:-false}"
  "PROFILE_PHOTO_MAX_MB=${PROFILE_PHOTO_MAX_MB:-10}"
  "DATA_POINT_EXTRACTOR=${DATA_POINT_EXTRACTOR:-rules}"
  "PROFILE_FACT_DEEP_EXTRACT_INTERVAL=${PROFILE_FACT_DEEP_EXTRACT_INTERVAL:-5}"
)

optional_env_names=(
  AGENT_RECENT_MESSAGE_LIMIT
  AGENT_CONTEXT_SOURCE_LIMIT
  AGENT_CONTEXT_SOURCE_CHAR_LIMIT
  AGENT_STYLE_CONTEXT_CHAR_LIMIT
  AGENT_CONTEXT_TOTAL_CHAR_BUDGET
  GROQ_MODEL
  GROQ_AVAILABLE_MODELS
  GROQ_RPD_LIMIT
  GROQ_TPD_LIMIT
  GROQ_RPM_LIMIT
  GROQ_TPM_LIMIT
  DEEPINFRA_MODEL
  DEEPINFRA_AVAILABLE_MODELS
  DEEPINFRA_BASE_URL
  DEEPINFRA_INPUT_COST_PER_1M
  DEEPINFRA_OUTPUT_COST_PER_1M
  DEEPINFRA_TIMEOUT_SECONDS
  FIREWORKS_MODEL
  FIREWORKS_AVAILABLE_MODELS
  FIREWORKS_INPUT_COST_PER_1M
  FIREWORKS_OUTPUT_COST_PER_1M
  FIREWORKS_TIMEOUT_SECONDS
  OLLAMA_BASE_URL
  OLLAMA_MODEL
  OLLAMA_AVAILABLE_MODELS
  PROFILE_PHOTO_GCS_BUCKET
  PROFILE_PHOTO_GCS_PREFIX
  PROFILE_PHOTO_GCS_PUBLIC_BASE_URL
  PROFILE_PHOTO_GCS_PUBLIC_READ
  DATA_POINT_LLM_CONTEXT_CHAR_LIMIT
  DATA_POINT_LLM_MAX_POINTS
)

for name in "${optional_env_names[@]}"; do
  if [ -n "${!name:-}" ]; then
    env_vars+=("$name=${!name}")
  fi
done

update_args=(
  run services update "$GCP_SERVICE"
  --region "$GCP_REGION"
  --update-env-vars "$(join_gcloud_dict_args "${env_vars[@]}")"
)

if [ "${#filtered_secret_args[@]}" -gt 0 ]; then
  update_args+=(--update-secrets "$(join_by_comma "${filtered_secret_args[@]}")")
fi

if [ -n "${GCP_CLOUDSQL_CONNECTION_NAME:-}" ]; then
  update_args+=(--add-cloudsql-instances "$GCP_CLOUDSQL_CONNECTION_NAME")
fi

if [ -n "${GCP_RUNTIME_SERVICE_ACCOUNT:-}" ]; then
  update_args+=(--service-account "$GCP_RUNTIME_SERVICE_ACCOUNT")
fi

gcloud "${update_args[@]}"

echo "Cloud Run env synced: $GCP_SERVICE"
