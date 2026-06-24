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

JOB_NAME="${JOB_NAME:-${GCP_SERVICE}-encrypt-backfill}"
DRY_RUN="${DRY_RUN:-true}"

gcloud config set project "$GCP_PROJECT_ID"

IMAGE_URI="$(gcloud run services describe "$GCP_SERVICE" \
  --region "$GCP_REGION" \
  --format='value(spec.template.spec.containers[0].image)')"

command_args=(python scripts/encrypt_existing_sensitive_data.py)
if [ "$DRY_RUN" = "true" ]; then
  command_args+=(--dry-run)
fi
if [ -n "${USER_ID:-}" ]; then
  command_args+=(--user-id "$USER_ID")
fi

secret_args=(
  "$(optional_secret_arg DATABASE_URL "$DATABASE_URL_SECRET")"
  "$(optional_secret_arg ENCRYPTION_MASTER_KEY "$ENCRYPTION_MASTER_KEY_SECRET")"
)

job_args=(
  run jobs deploy "$JOB_NAME"
  --image "$IMAGE_URI"
  --region "$GCP_REGION"
  --set-secrets "$(join_by_comma "${secret_args[@]}")"
  --command python
  --args "$(join_by_comma "${command_args[@]:1}")"
)

if [ -n "${GCP_CLOUDSQL_CONNECTION_NAME:-}" ]; then
  job_args+=(--add-cloudsql-instances "$GCP_CLOUDSQL_CONNECTION_NAME")
fi

gcloud "${job_args[@]}"
gcloud run jobs execute "$JOB_NAME" --region "$GCP_REGION" --wait
