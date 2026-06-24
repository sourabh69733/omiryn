#!/usr/bin/env bash
set -euo pipefail

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

export PYTHONPATH="${PYTHONPATH:-src}"

python - <<'PY'
from sqlalchemy import text
from storage import ENGINE, database_url

with ENGINE.connect() as connection:
    connection.execute(text("SELECT 1"))

print(f"Database connection OK: {database_url()}")
PY
