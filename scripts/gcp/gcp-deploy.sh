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
require_artifact_repository_name

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
  "$(optional_secret_arg GROQ_API_KEY "${GROQ_API_KEY_SECRET:-}")"
  "$(optional_secret_arg OPENAI_API_KEY "${OPENAI_API_KEY_SECRET:-}")"
)
filtered_secret_args=()
for value in "${secret_args[@]}"; do
  if [ -n "$value" ]; then
    filtered_secret_args+=("$value")
  fi
done

env_vars=(
  "AUTH_PROVIDER=${AUTH_PROVIDER:-supabase}"
  "AUTH_REQUIRED=${AUTH_REQUIRED:-true}"
  "DB_DISABLE_POOL=${DB_DISABLE_POOL:-true}"
  "AGENT_PROVIDER=${AGENT_PROVIDER:-mock}"
  "PROFILE_DEBUG_DATA_ENABLED=${PROFILE_DEBUG_DATA_ENABLED:-false}"
  "PROFILE_PHOTO_MAX_MB=${PROFILE_PHOTO_MAX_MB:-10}"
)

if [ -n "${PROFILE_PHOTO_GCS_BUCKET:-}" ]; then
  env_vars+=("PROFILE_PHOTO_GCS_BUCKET=$PROFILE_PHOTO_GCS_BUCKET")
fi

if [ -n "${PROFILE_PHOTO_GCS_PREFIX:-}" ]; then
  env_vars+=("PROFILE_PHOTO_GCS_PREFIX=$PROFILE_PHOTO_GCS_PREFIX")
fi

if [ -n "${PROFILE_PHOTO_GCS_PUBLIC_BASE_URL:-}" ]; then
  env_vars+=("PROFILE_PHOTO_GCS_PUBLIC_BASE_URL=$PROFILE_PHOTO_GCS_PUBLIC_BASE_URL")
fi

deploy_args=(
  run deploy "$GCP_SERVICE"
  --image "$IMAGE_URI"
  --region "$GCP_REGION"
  --platform managed
  --allow-unauthenticated
  --set-env-vars "$(join_by_comma "${env_vars[@]}")"
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
