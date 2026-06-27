#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

docker compose up -d db

echo "Postgres service started."
echo "Local DATABASE_URL example:"
echo "postgresql+psycopg://${POSTGRES_USER:-omiryn}:${POSTGRES_PASSWORD:-omiryn}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-omiryn}"
