#!/usr/bin/env bash
set -euo pipefail

GCP_ENV_FILE="${GCP_ENV_FILE:-.gcp.env}"

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
