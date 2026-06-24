#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_ARTIFACT_REPOSITORY

gcloud config set project "$GCP_PROJECT_ID"

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

echo "GCP bootstrap complete."
