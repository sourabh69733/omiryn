#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
  source "$PROJECT_ROOT/.venv/bin/activate"
fi

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

export PYTHONPATH="${PYTHONPATH:-$PROJECT_ROOT/src}"

python - <<'PY'
from sqlalchemy import text
from storage import ENGINE, database_url

with ENGINE.connect() as connection:
    connection.execute(text("SELECT 1"))

print(f"Database connection OK: {database_url()}")
PY
