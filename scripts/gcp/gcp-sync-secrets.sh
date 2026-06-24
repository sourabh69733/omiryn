#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID

sync_secret() {
  local secret_name_var="$1"
  local value_var="$2"
  local required="${3:-optional}"
  local secret_name="${!secret_name_var:-}"
  local value="${!value_var:-}"

  if [ -z "$secret_name" ]; then
    if [ "$required" = "required" ]; then
      echo "Missing required secret-name variable: $secret_name_var" >&2
      exit 1
    fi
    echo "Skipping $value_var: $secret_name_var is not set."
    return
  fi
  require_secret_name "$secret_name" "$secret_name_var"

  if [ -z "$value" ]; then
    if [ "$required" = "required" ]; then
      echo "Missing required secret value: $value_var" >&2
      exit 1
    fi
    echo "Skipping $value_var: value is empty."
    return
  fi

  "$SCRIPT_DIR/gcp-set-secret.sh" "$secret_name" "$value_var"
}

# sync_secret DATABASE_URL_SECRET DATABASE_URL required
# sync_secret ENCRYPTION_MASTER_KEY_SECRET ENCRYPTION_MASTER_KEY required
sync_secret SUPABASE_URL_SECRET SUPABASE_URL required
sync_secret SUPABASE_ANON_KEY_SECRET SUPABASE_ANON_KEY required
sync_secret GROQ_API_KEY_SECRET GROQ_API_KEY required
# sync_secret OPENAI_API_KEY_SECRET OPENAI_API_KEY optional

echo "GCP secrets synced."
