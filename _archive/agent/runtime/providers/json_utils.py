from __future__ import annotations

import json
from typing import Any

from .errors import AgentProviderError


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise AgentProviderError("Model did not return a JSON object.")
    return json.loads(cleaned[start : end + 1])
