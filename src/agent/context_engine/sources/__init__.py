"""Context sources for a reply, one module per source. Each returns a list of
{"source_type", "title", "content", "metadata"} dicts (empty when it has nothing to add);
`assembly/sources.py` puts them together.

Always on: user_card, sessions, summary, memories, might_fit, past_lines, self_notes,
open_questions, reply_feedback, shared_chats, texting_style. Attached notes and styles: attached,
whatsapp. Before v3 only: legacy.
"""
