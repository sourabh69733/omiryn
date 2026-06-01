#!/usr/bin/env bash
set -euo pipefail

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-src}"

HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-8000}"

python -m uvicorn omiryn.api.main:app --reload --host "$HOST" --port "$PORT"
