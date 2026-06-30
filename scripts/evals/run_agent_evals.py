#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/omiryn_eval_test.db")
os.environ.setdefault("AGENT_PROVIDER", "mock")
os.environ.setdefault("AUTH_REQUIRED", "false")

from agent.evals.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
