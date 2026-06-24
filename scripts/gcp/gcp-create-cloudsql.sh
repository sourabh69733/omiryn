#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/gcp-common.sh
source "$SCRIPT_DIR/gcp-common.sh"

require_var GCP_PROJECT_ID
require_var GCP_REGION
require_var GCP_SQL_INSTANCE
require_var GCP_SQL_DATABASE
require_var GCP_SQL_USER

GCP_SQL_TIER="${GCP_SQL_TIER:-db-f1-micro}"
GCP_SQL_EDITION="${GCP_SQL_EDITION:-ENTERPRISE}"
GCP_SQL_VERSION="${GCP_SQL_VERSION:-POSTGRES_16}"

gcloud config set project "$GCP_PROJECT_ID"

if ! gcloud sql instances describe "$GCP_SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$GCP_SQL_INSTANCE" \
    --database-version "$GCP_SQL_VERSION" \
    --region "$GCP_REGION" \
    --edition "$GCP_SQL_EDITION" \
    --tier "$GCP_SQL_TIER" \
    --storage-size 10GB \
    --backup-start-time 03:00 \
    --availability-type zonal
fi

if ! gcloud sql databases describe "$GCP_SQL_DATABASE" \
  --instance "$GCP_SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql databases create "$GCP_SQL_DATABASE" --instance "$GCP_SQL_INSTANCE"
fi

if [ -n "${DB_PASSWORD:-}" ]; then
  if ! gcloud sql users list --instance "$GCP_SQL_INSTANCE" \
    --format "value(name)" | grep -qx "$GCP_SQL_USER"; then
    gcloud sql users create "$GCP_SQL_USER" \
      --instance "$GCP_SQL_INSTANCE" \
      --password "$DB_PASSWORD"
  else
    echo "Cloud SQL user already exists: $GCP_SQL_USER"
  fi
else
  echo "DB_PASSWORD not set. Skipping Cloud SQL user creation."
fi

CONNECTION_NAME="$(gcloud sql instances describe "$GCP_SQL_INSTANCE" --format='value(connectionName)')"
echo "Cloud SQL ready."
echo "Connection name: $CONNECTION_NAME"
echo "Cloud Run DATABASE_URL for Unix socket:"
echo "postgresql+psycopg://${GCP_SQL_USER}:<password>@/${GCP_SQL_DATABASE}?host=/cloudsql/${CONNECTION_NAME}"
