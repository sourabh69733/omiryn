"""The reply models a user can pick in Profile > Advanced, each with a short name and strong point.

Only models the server offers (`available_models` for the provider) are shown. A model missing
from MODEL_LABELS still shows, named by its ID, so adding one to the env never hides it.

Claude models are offered apart from the provider's list, and only for replies:
AGENT_REPLY_MODEL names the model that writes replies for everyone who has not picked one, and
CLAUDE_REPLY_MODELS (comma-separated) adds Claude models to the picker. Both need a Claude key;
without one they are ignored. Everything behind the reply (memory, summaries) stays on the
provider's model.
"""

from __future__ import annotations

import os
from typing import Any

from storage import get_reply_model

from agent.providers.gateway.claude import claude_key, is_claude

from .config import agent_runtime_status

# Model ID -> (short name, 2-3 words on what it is good at). Edit freely; it is product copy.
MODEL_LABELS: dict[str, tuple[str, str]] = {
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506": ("Mistral Small", "lively and casual"),
    "google/gemma-4-31B-it": ("Gemma", "warm, longer replies"),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": ("Llama 3.3", "steady and balanced"),
    "openai/gpt-oss-120b": ("GPT-OSS 120B", "careful and thoughtful"),
    "openai/gpt-oss-20b": ("GPT-OSS 20B", "fast and light"),
    "claude-haiku-5-5": ("Claude Haiku", "quick and natural"),
    "claude-sonnet-5-5": ("Claude Sonnet", "reads between the lines"),
    "claude-opus-5-5": ("Claude Opus", "deepest, slowest"),
}


def server_reply_model() -> str | None:
    """AGENT_REPLY_MODEL when it can be used: any model of the provider, or a Claude model with a key."""
    named = os.getenv("AGENT_REPLY_MODEL", "").strip()
    if not named or (is_claude(named) and not claude_key()):
        return None
    return named


def claude_reply_models() -> list[str]:
    """The Claude models offered in the picker (CLAUDE_REPLY_MODELS); none without a key."""
    if not claude_key():
        return []
    named = [model.strip() for model in os.getenv("CLAUDE_REPLY_MODELS", "").split(",")]
    return list(dict.fromkeys(model for model in named if is_claude(model)))


def model_choices(runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    """{"default": model ID, "choices": [{"id", "name", "strength"}]} for the picker."""
    runtime = runtime or agent_runtime_status()
    default = server_reply_model() or str(runtime.get("model") or "")
    available = [str(model) for model in runtime.get("available_models") or [] if model]
    available.extend(model for model in claude_reply_models() if model not in available)
    if default and default not in available:
        available.insert(0, default)
    choices = []
    for model in available:
        name, strength = MODEL_LABELS.get(model, (model.split("/")[-1], ""))
        choices.append({"id": model, "name": name, "strength": strength})
    return {"default": default, "choices": choices}


def preferred_reply_model(user_id: str | None) -> str | None:
    """The user's pick when the server still offers it; otherwise AGENT_REPLY_MODEL when set, else
    None, the provider's current model.

    A chat's stored model is the default from the day it was made: following it kept old chats on a
    model the server had moved away from, so changing the default never reached them.
    """
    picked = get_reply_model(user_id) if user_id else None
    if not picked:
        return server_reply_model()
    offered = {choice["id"] for choice in model_choices()["choices"]}
    return picked if picked in offered else server_reply_model()


__all__ = ["MODEL_LABELS", "claude_reply_models", "model_choices", "preferred_reply_model", "server_reply_model"]
