#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_SERVICE

gcloud config set project "$GCP_PROJECT_ID"

gcloud run services logs read "$GCP_SERVICE" \
  --region "$GCP_REGION" \
  --limit "${LIMIT:-100}"
