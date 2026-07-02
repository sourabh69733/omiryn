from __future__ import annotations


def tone_module_prompt(tone: str) -> str:
    prompts = {
        "auto": (
            "Tone setting: Auto. Match the user's natural tone from recent messages and imported "
            "speaking-style context. If signals conflict, stay warm, clear, brief, and natural."
        ),
        "casual": "Tone setting: Casual. Use relaxed, simple language without sounding sloppy.",
        "warm": "Tone setting: Warm. Be gentle, supportive, and emotionally clear.",
        "formal": "Tone setting: Formal. Be polished, structured, and respectful.",
        "direct": "Tone setting: Direct. Be concise, specific, and low-fluff.",
        "playful": "Tone setting: Playful. Be light and witty while staying respectful.",
    }
    return prompts.get(tone, prompts["auto"])
