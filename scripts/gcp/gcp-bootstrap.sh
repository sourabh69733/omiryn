#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_ARTIFACT_REPOSITORY
require_artifact_repository_name

gcloud config set project "$GCP_PROJECT_ID"

PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')"
CLOUD_BUILD_SERVICE_ACCOUNTS=(
  "${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
  "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
)

gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com

if ! gcloud artifacts repositories describe "$GCP_ARTIFACT_REPOSITORY" \
  --location "$GCP_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$GCP_ARTIFACT_REPOSITORY" \
    --repository-format docker \
    --location "$GCP_REGION" \
    --description "Omiryn application images"
fi

for service_account in "${CLOUD_BUILD_SERVICE_ACCOUNTS[@]}"; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:${service_account}" \
    --role roles/storage.objectViewer \
    --quiet

  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:${service_account}" \
    --role roles/artifactregistry.writer \
    --quiet
done

echo "GCP bootstrap complete."
