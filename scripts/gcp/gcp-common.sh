#!/usr/bin/env bash
set -euo pipefail

GCP_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$GCP_COMMON_DIR/../.." && pwd)}"
GCP_ENV_FILE="${GCP_ENV_FILE:-$PROJECT_ROOT/.gcp.env}"

if [ -f "$GCP_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$GCP_ENV_FILE"
  set +a
fi

require_var() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment variable: $name" >&2
    echo "Create .gcp.env from scripts/gcp-env.example or export $name." >&2
    exit 1
  fi
}

require_artifact_repository_name() {
  if [[ ! "${GCP_ARTIFACT_REPOSITORY:-}" =~ ^[a-z]([a-z0-9-]*[a-z0-9])?$ ]]; then
    echo "Invalid GCP_ARTIFACT_REPOSITORY: ${GCP_ARTIFACT_REPOSITORY:-<empty>}" >&2
    echo "Loaded env file: $GCP_ENV_FILE" >&2
    echo "Use only the Artifact Registry repository id, for example: omiryn" >&2
    echo "Do not use the full registry URL like asia-south1-docker.pkg.dev/PROJECT/REPO." >&2
    exit 1
  fi
}

require_secret_name() {
  local secret_name="$1"
  local label="${2:-secret name}"
  if [[ ! "$secret_name" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Invalid $label: $secret_name" >&2
    echo "Use only the Secret Manager secret id, for example: omiryn-supabase-url" >&2
    echo "Do not use a URL, token, API key, or full resource path here." >&2
    exit 1
  fi
}

optional_secret_arg() {
  local env_name="$1"
  local secret_name="$2"
  if [ -n "$secret_name" ]; then
    printf "%s=%s:latest" "$env_name" "$secret_name"
  fi
}

join_by_comma() {
  local IFS=","
  echo "$*"
}
