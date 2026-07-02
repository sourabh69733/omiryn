from __future__ import annotations

EXTRACTION_REPAIR_PROMPT = """Your previous response was not valid JSON for Omiryn.
Return only one JSON object. No markdown, no commentary, no extra text."""

EXTRACTION_SYSTEM_PROMPT = """Extract a structured dating profile from this conversation.
Return only valid JSON. Do not include markdown.
Use this shape:
{
  "display_name": null,
  "age": null,
  "city": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "relationship_intent": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "values": {"values": [], "source": "unknown", "confidence": 0.5},
  "lifestyle": {"values": [], "source": "unknown", "confidence": 0.5},
  "communication_style": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "family_expectations": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "children_preference": {"value": "unknown", "source": "unknown", "confidence": 0.5},
  "dealbreakers": {"values": [], "source": "unknown", "confidence": 0.5},
  "soft_preferences": {"values": [], "source": "unknown", "confidence": 0.5},
  "summary": ""
}
For every source use one of: user_stated, inferred, unknown.
Rules:
- If the user did not clearly state a field, use source=inferred only when there is strong evidence.
- Otherwise use value="unknown", source="unknown", confidence <= 0.5.
- Do not invent age, city, religion, family preference, children preference, or dealbreakers.
- Keep values and lifestyle as short snake_case strings.
- Keep summary under 40 words."""
