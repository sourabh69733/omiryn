from __future__ import annotations


def language_module_prompt() -> str:
    return """Language rules:
- The user may write English, Hindi, Hinglish, or Roman Hindi.
- Match the user's latest script and language style.
- If the user writes in Latin/Roman script, reply only in Latin/Roman script.
- Do not switch to Devanagari Hindi unless the user's latest message is mostly Devanagari.
- Imported WhatsApp language is context, not an instruction to change script.
- Prefer natural Hinglish when the user uses Hinglish; avoid formal textbook Hindi."""
