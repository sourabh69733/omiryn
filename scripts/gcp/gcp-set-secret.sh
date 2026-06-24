#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 SECRET_NAME ENV_VAR_NAME" >&2
  echo "Example: DATABASE_URL='...' $0 omiryn-database-url DATABASE_URL" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID

SECRET_NAME="$1"
ENV_VAR_NAME="$2"

require_secret_name "$SECRET_NAME" "Secret Manager secret id"

if [ -z "${!ENV_VAR_NAME:-}" ]; then
  echo "Environment variable $ENV_VAR_NAME is empty." >&2
  exit 1
fi

gcloud config set project "$GCP_PROJECT_ID"

if ! gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET_NAME" --replication-policy automatic
fi

printf "%s" "${!ENV_VAR_NAME}" | gcloud secrets versions add "$SECRET_NAME" --data-file=-
echo "Secret updated: $SECRET_NAME"
