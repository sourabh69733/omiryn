from __future__ import annotations

DEEP_FACT_EXTRACTION_SYSTEM_PROMPT = """Extract private Omiryn matching memory facts from the conversation.
Return only valid JSON. Do not include markdown.
Use this shape:
{
  "facts": [
    {
      "category": "values",
      "key": "mutual_respect",
      "label": "Values mutual respect",
      "value": {"kind": "mutual_respect", "detail": "Short detail"},
      "confidence": 0.72,
      "evidence": "Short user quote or paraphrase"
    }
  ]
}
Rules:
- Extract only facts about the user, not the assistant or other people.
- Prefer many small facts over broad summaries.
- Useful categories: dating_intent, values, lifestyle, communication, conflict_style,
  attachment_style, emotional_patterns, family_context, partner_preferences,
  dealbreakers, attraction_patterns, goals, constraints, personality.
- For dating_intent, only extract the specific outcome or seriousness: exploring,
  long_term, short_term, casual, marriage, commitment. Do not create generic
  points like "looking for someone", "open to relationship", or "wants dating".
- Do not invent. If weakly inferred, confidence must be <= 0.45.
- Do not diagnose medical or mental health conditions.
- Keep labels under 12 words and evidence under 30 words.
- Return at most 25 facts."""

DATA_POINT_EXTRACTION_SYSTEM_PROMPT = """Extract high-quality Omiryn data point candidates.
Return only valid JSON. Do not include markdown.
Use this shape:
{
  "data_points": [
    {
      "category": "conversation_context",
      "key": "short_snake_case_key",
      "label": "Short meaningful memory",
      "meaning": "Why this will be useful later",
      "value": {"kind": "short_snake_case_key", "detail": "Short structured detail"},
      "confidence": 0.72,
      "evidence": ["Short quote or paraphrase"],
      "used_for_chat_context": true,
      "used_for_matching": false,
      "used_for_style": false,
      "privacy_level": "normal"
    }
  ]
}
Rules:
- Extract meaning, not keywords. Do not create points like "talked about location".
- Only include points that would be useful in a future chat, matching, or style adaptation.
- For relationship_intent/dating_intent, only include a specific outcome or
  seriousness. Skip obvious dating-app defaults like looking for someone,
  wanting a partner, or being open to dating.
- Every point must have evidence from the supplied text.
- Prefer fewer strong points over many weak ones. Return at most 12 points.
- Do not invent. If uncertain, skip it.
- Avoid sensitive/private third-party details unless necessary for context; set privacy_level=private if included.
- Valid categories: conversation_context, relationship_intent, communication_style,
  tone_traits, important_people, recent_events, preferences, boundaries, matching_signals."""

DATA_POINT_REVIEW_SYSTEM_PROMPT = """Review Omiryn rule-generated data point candidates.
Return only valid JSON. Do not include markdown.
Use this shape:
{
  "reviews": [
    {
      "candidate_key": "candidate_key_from_input",
      "decision": "approve",
      "what_we_learned": "Meaningful memory learned from the evidence",
      "why_it_matters": "Why this is useful later",
      "confidence": 0.78,
      "evidence": ["Short quote or paraphrase from source"],
      "usage": {
        "chat_context": true,
        "matching": false,
        "style": false,
        "debug_only": false
      },
      "final_point": {
        "category": "conversation_context",
        "key": "short_snake_case_key",
        "label": "Short meaningful memory",
        "meaning": "Why this will be useful later",
        "value": {"kind": "short_snake_case_key", "detail": "Short structured detail"},
        "privacy_level": "normal"
      },
      "rejection_reason": null
    }
  ]
}
Decision rules:
- approve: candidate is already good; final_point may lightly normalize it.
- rewrite: candidate is useful but label/meaning/category should be improved; final_point is required.
- merge: candidate should be folded into a broader final_point; final_point is required.
- reject: candidate is weak/random/private/unsupported; rejection_reason is required and final_point must be null.
Review questions:
- What did we learn?
- Why does it matter?
- How confident are we?
- Where did it come from?
- Should it be used for chat, matching, style, or debug only?
Rules:
- Judge meaning, not keywords.
- Reject generic points like "talked about location" unless rewritten into useful memory.
- Every approved/rewrite/merge review needs evidence.
- Do not invent evidence or facts outside the supplied source text.
- Prefer fewer stronger final points."""
