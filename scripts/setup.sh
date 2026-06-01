#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
fi

python -m unittest discover -s tests
