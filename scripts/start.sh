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

MODE="${START_MODE:-development}"
BACKEND_HOST="${APP_HOST:-127.0.0.1}"
BACKEND_PORT="${APP_PORT:-8001}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [ "$MODE" = "production" ]; then
  npm run frontend:build
  exec python -m uvicorn api.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
fi

api_pid=""
web_pid=""

cleanup() {
  trap - EXIT INT TERM
  if [ -n "$web_pid" ]; then
    kill "$web_pid" 2>/dev/null || true
  fi
  if [ -n "$api_pid" ]; then
    kill "$api_pid" 2>/dev/null || true
  fi
  if [ -n "$web_pid" ]; then
    wait "$web_pid" 2>/dev/null || true
  fi
  if [ -n "$api_pid" ]; then
    wait "$api_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

python -m uvicorn api.main:app \
  --reload \
  --reload-dir src \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" &
api_pid=$!

VITE_API_PROXY_TARGET="http://127.0.0.1:${BACKEND_PORT}" \
  npm run frontend:dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
web_pid=$!

echo "Omiryn development server"
echo "App: http://${FRONTEND_HOST}:${FRONTEND_PORT}/app"
echo "API: http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "React changes use Vite HMR; Python changes restart Uvicorn."

status=0
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$api_pid" 2>/dev/null; then
  wait "$api_pid" || status=$?
else
  wait "$web_pid" || status=$?
fi

exit "$status"
