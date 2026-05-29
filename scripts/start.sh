#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-src}"

HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-8000}"

python -m uvicorn omiryn.api.main:app --reload --host "$HOST" --port "$PORT"
