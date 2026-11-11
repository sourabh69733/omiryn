"""The reply models a user can pick in Profile > Advanced, each with a short name and strong point.

Only models the server offers (`available_models` for the provider) are shown. A model missing
from MODEL_LABELS still shows, named by its ID, so adding one to the env never hides it.
"""

from __future__ import annotations

from typing import Any

from storage import get_reply_model

from .config import agent_runtime_status

# Model ID -> (short name, 2-3 words on what it is good at). Edit freely; it is product copy.
MODEL_LABELS: dict[str, tuple[str, str]] = {
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506": ("Mistral Small", "lively and casual"),
    "google/gemma-4-31B-it": ("Gemma", "warm, longer replies"),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": ("Llama 3.3", "steady and balanced"),
    "openai/gpt-oss-120b": ("GPT-OSS 120B", "careful and thoughtful"),
    "openai/gpt-oss-20b": ("GPT-OSS 20B", "fast and light"),
}


def model_choices(runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    """{"default": model ID, "choices": [{"id", "name", "strength"}]} for the picker."""
    runtime = runtime or agent_runtime_status()
    default = str(runtime.get("model") or "")
    available = [str(model) for model in runtime.get("available_models") or [] if model]
    if default and default not in available:
        available.insert(0, default)
    choices = []
    for model in available:
        name, strength = MODEL_LABELS.get(model, (model.split("/")[-1], ""))
        choices.append({"id": model, "name": name, "strength": strength})
    return {"default": default, "choices": choices}


def preferred_reply_model(user_id: str | None) -> str | None:
    """The user's pick when the server still offers it; otherwise None, the server's current model.

    A chat's stored model is the default from the day it was made: following it kept old chats on a
    model the server had moved away from, so changing the default never reached them.
    """
    picked = get_reply_model(user_id) if user_id else None
    if not picked:
        return None
    offered = {choice["id"] for choice in model_choices()["choices"]}
    return picked if picked in offered else None


__all__ = ["MODEL_LABELS", "model_choices", "preferred_reply_model"]
