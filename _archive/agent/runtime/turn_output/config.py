from __future__ import annotations

import os


def turn_output_v2_enabled() -> bool:
    version = os.getenv("AGENT_TURN_OUTPUT_VERSION", "v2").strip().lower()
    return version == "v2"
