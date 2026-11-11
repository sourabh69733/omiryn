"""Code facts about who made Omi: does a draft say which company or model made or runs it?

Omi runs on a model from another lab, and that lab's model sometimes speaks for itself: "I was
developed by Google", or a guess the other way, "I'm not made by Google". Omiryn's answer is honest
but general (Omiryn made Omi, on an AI model from another company), so any sentence where Omi names
the company or model behind itself gets one rewrite. Other mentions, such as "it works like
ChatGPT" or "Google Maps", are fine: the sentence must speak about Omi and say who made or runs it.
"""

from __future__ import annotations

import re

_LABS = (
    r"google|deepmind|openai|open ai|meta|facebook|mistral|anthropic|microsoft|alibaba|deepseek|"
    r"deepinfra|nvidia|xai|hugging ?face"
)
_MODELS = r"gemma|gemini|bard|chat ?gpt|gpt[- ]?\d[\w.-]*|llama|claude|qwen|grok|copilot|mixtral"
_NAME = rf"(?:{_LABS}|{_MODELS})"

# A first-person word in English or Hinglish: the sentence talks about Omi itself.
_ME = re.compile(r"\b(?:i|i'm|im|i've|me|my|myself|main|mai|mein|mujhe|mujh|mera|meri|mere|maine)\b", re.IGNORECASE)

_CLAIMS = (
    # "developed by Google", "trained by OpenAI", "based on Gemma", "running on Llama"
    re.compile(
        rf"\b(?:made|developed|created|built|trained|designed|programmed|owned|powered|run|running|based)"
        rf"\s+(?:by|on|from)\s+(?:the\s+)?(?:{_NAME})\b",
        re.IGNORECASE,
    ),
    # "Google ne banaya", "OpenAI dwara train", "Gemma pe chalta hoon"
    re.compile(
        rf"\b{_NAME}\b\s+(?:ne|dwara|dvara|ke dwara|ki taraf se|pe|par)\s+"
        r"(?:\w+\s+)?(?:banaya|banayi|bana|banaa|develop|create|train|tayyar|chalta|chalti|based)",
        re.IGNORECASE,
    ),
    # "Google ka model hoon", "Gemma ka version"
    re.compile(rf"\b{_NAME}\b\s+(?:ka|ki|ke)\s+(?:banaya|bana|model|ai|product|version|assistant)\b", re.IGNORECASE),
    # "I am Gemma", "I'm a Gemini model", "main Gemma hoon"
    re.compile(
        rf"\b(?:i am|i'm|im|main|mai)\s+(?:a|an|the|ek)?\s*(?:{_NAME})\b(?![\s-]*(?:jaisa|jaisi|jaise|like|se|wala|wali))",
        re.IGNORECASE,
    ),
    re.compile(rf"\b{_NAME}\b\s+(?:model\s+)?(?:hoon|hun|hu)\b", re.IGNORECASE),
)

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def maker_claim(reply: str) -> str | None:
    """The sentence where the reply says which company or model made or runs Omi, or None."""
    for match in _SENTENCE.finditer(reply or ""):
        sentence = match.group(0).strip()
        if sentence and _ME.search(sentence) and any(pattern.search(sentence) for pattern in _CLAIMS):
            return sentence
    return None


def maker_claim_reason(quote: str) -> str:
    return (
        f'it says which company or model made or runs you ("{quote[:200]}"). Omiryn made you, and you '
        "run on an AI model from another company. Say that in your own words, without naming or ruling "
        "out any company or model"
    )


__all__ = ["maker_claim", "maker_claim_reason"]
