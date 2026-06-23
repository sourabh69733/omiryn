#!/usr/bin/env bash
set -euo pipefail

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-src}"

python scripts/encrypt_existing_sensitive_data.py "$@"
