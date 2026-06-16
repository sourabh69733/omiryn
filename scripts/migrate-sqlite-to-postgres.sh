#!/usr/bin/env bash
set -euo pipefail

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-src}"

python scripts/migrate_sqlite_to_postgres.py "$@"
