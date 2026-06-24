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
from storage import database_url, init_db

init_db()
print(f"Database initialized: {database_url()}")
PY
