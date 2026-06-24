#!/usr/bin/env bash
set -euo pipefail

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-src}"

python scripts/assign_legacy_data_to_user.py "$@"
