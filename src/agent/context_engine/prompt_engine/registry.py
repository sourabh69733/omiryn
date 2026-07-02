from __future__ import annotations

import os

from agent.context_engine.prompt_engine.models import PromptBehaviorVersion
from agent.context_engine.prompt_engine.versions.v1 import V1_PROMPT_VERSION
from agent.context_engine.prompt_engine.versions.v2 import V2_PROMPT_VERSION

DEFAULT_PROMPT_VERSION_ID = "v1"

_PROMPT_VERSIONS = {
    V1_PROMPT_VERSION.version_id: V1_PROMPT_VERSION,
    V1_PROMPT_VERSION.name: V1_PROMPT_VERSION,
    V2_PROMPT_VERSION.version_id: V2_PROMPT_VERSION,
    V2_PROMPT_VERSION.name: V2_PROMPT_VERSION,
}


def configured_prompt_version_id() -> str:
    return os.getenv("AGENT_BEHAVIOR_VERSION", DEFAULT_PROMPT_VERSION_ID).strip() or DEFAULT_PROMPT_VERSION_ID


def get_prompt_behavior_version(version_id: str | None = None) -> PromptBehaviorVersion:
    requested = (version_id or configured_prompt_version_id()).strip()
    return _PROMPT_VERSIONS.get(requested) or _PROMPT_VERSIONS[DEFAULT_PROMPT_VERSION_ID]


def available_prompt_versions() -> list[PromptBehaviorVersion]:
    seen: set[str] = set()
    versions: list[PromptBehaviorVersion] = []
    for version in _PROMPT_VERSIONS.values():
        if version.version_id in seen:
            continue
        seen.add(version.version_id)
        versions.append(version)
    return versions
