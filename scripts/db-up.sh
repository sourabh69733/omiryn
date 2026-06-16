#!/usr/bin/env bash
set -euo pipefail

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

docker compose up -d db

echo "Postgres service started."
echo "Local DATABASE_URL example:"
echo "postgresql+psycopg://${POSTGRES_USER:-omiryn}:${POSTGRES_PASSWORD:-omiryn}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-omiryn}"
