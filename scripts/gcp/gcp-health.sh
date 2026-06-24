#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_SERVICE

gcloud config set project "$GCP_PROJECT_ID"

SERVICE_URL="$(gcloud run services describe "$GCP_SERVICE" \
  --region "$GCP_REGION" \
  --format='value(status.url)')"

curl -fsS "$SERVICE_URL/health"
echo
