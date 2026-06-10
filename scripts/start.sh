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

HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-8001}"
RELOAD="${APP_RELOAD:-false}"

if [ "$RELOAD" = "true" ]; then
  python -m uvicorn api.main:app --reload --host "$HOST" --port "$PORT"
else
  python -m uvicorn api.main:app --host "$HOST" --port "$PORT"
fi
