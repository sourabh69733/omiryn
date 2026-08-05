#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_SERVICE
require_var GCP_ARTIFACT_REPOSITORY
require_var DATABASE_URL_SECRET
require_var ENCRYPTION_MASTER_KEY_SECRET
require_var SUPABASE_URL_SECRET
require_var SUPABASE_ANON_KEY_SECRET
require_var PROFILE_PHOTO_GCS_BUCKET
require_artifact_repository_name

if [ -z "${ADMIN_EMAILS:-}" ] && [ -z "${ADMIN_USER_IDS:-}" ]; then
  echo "Missing required admin allowlist: set ADMIN_EMAILS or ADMIN_USER_IDS." >&2
  exit 1
fi

IMAGE_TAG="${IMAGE_TAG:-$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE_URI="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${GCP_ARTIFACT_REPOSITORY}/${GCP_SERVICE}:${IMAGE_TAG}"

gcloud config set project "$GCP_PROJECT_ID"

gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com

if ! gcloud artifacts repositories describe "$GCP_ARTIFACT_REPOSITORY" \
  --location "$GCP_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$GCP_ARTIFACT_REPOSITORY" \
    --repository-format docker \
    --location "$GCP_REGION" \
    --description "Omiryn application images"
fi

PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SERVICE_ACCOUNT="${GCP_RUNTIME_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
CLOUD_BUILD_SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member "serviceAccount:${CLOUD_BUILD_SERVICE_ACCOUNT}" \
  --role roles/logging.logWriter \
  --quiet >/dev/null

if [ -n "${PROFILE_PHOTO_GCS_BUCKET:-}" ]; then
  if ! gcloud storage buckets describe "gs://${PROFILE_PHOTO_GCS_BUCKET}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${PROFILE_PHOTO_GCS_BUCKET}" \
      --location "$GCP_REGION" \
      --uniform-bucket-level-access
  fi
  gcloud storage buckets add-iam-policy-binding "gs://${PROFILE_PHOTO_GCS_BUCKET}" \
    --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role roles/storage.objectAdmin >/dev/null
  if [ "${PROFILE_PHOTO_GCS_PUBLIC_READ:-false}" = "true" ]; then
    gcloud storage buckets add-iam-policy-binding "gs://${PROFILE_PHOTO_GCS_BUCKET}" \
      --member allUsers \
      --role roles/storage.objectViewer >/dev/null
  fi
fi

echo "Building image: $IMAGE_URI"
gcloud builds submit "$PROJECT_ROOT" --tag "$IMAGE_URI"

secret_args=(
  "$(optional_secret_arg DATABASE_URL "$DATABASE_URL_SECRET")"
  "$(optional_secret_arg ENCRYPTION_MASTER_KEY "$ENCRYPTION_MASTER_KEY_SECRET")"
  "$(optional_secret_arg SUPABASE_URL "${SUPABASE_URL_SECRET:-}")"
  "$(optional_secret_arg SUPABASE_ANON_KEY "${SUPABASE_ANON_KEY_SECRET:-}")"
  "$(optional_secret_arg SECRET_KEY "${SECRET_KEY_SECRET:-}")"
  "$(optional_secret_arg GROQ_API_KEY "${GROQ_API_KEY_SECRET:-}")"
  "$(optional_secret_arg DEEPINFRA_API_KEY "${DEEPINFRA_API_KEY_SECRET:-}")"
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
  ADMIN_EMAILS
  ADMIN_USER_IDS
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
  USER_LIMIT_MONTH_DAYS
  USER_CHAT_MONTHLY_LIMIT
  USER_CONTEXT_IMPORT_MONTHLY_LIMIT
  USER_WHATSAPP_IMPORT_MONTHLY_LIMIT
)

for name in "${optional_env_names[@]}"; do
  if [ -n "${!name:-}" ]; then
    env_vars+=("$name=${!name}")
  fi
done

deploy_args=(
  run deploy "$GCP_SERVICE"
  --image "$IMAGE_URI"
  --region "$GCP_REGION"
  --platform managed
  --allow-unauthenticated
  --set-env-vars "$(join_gcloud_dict_args "${env_vars[@]}")"
)

if [ "${#filtered_secret_args[@]}" -gt 0 ]; then
  deploy_args+=(--set-secrets "$(join_by_comma "${filtered_secret_args[@]}")")
fi

if [ -n "${GCP_CLOUDSQL_CONNECTION_NAME:-}" ]; then
  deploy_args+=(--add-cloudsql-instances "$GCP_CLOUDSQL_CONNECTION_NAME")
fi

if [ -n "${GCP_RUNTIME_SERVICE_ACCOUNT:-}" ]; then
  deploy_args+=(--service-account "$GCP_RUNTIME_SERVICE_ACCOUNT")
fi

gcloud "${deploy_args[@]}"

SERVICE_URL="$(gcloud run services describe "$GCP_SERVICE" \
  --region "$GCP_REGION" \
  --format='value(status.url)')"

echo "Deployed image: $IMAGE_URI"
echo "Service URL: $SERVICE_URL"
