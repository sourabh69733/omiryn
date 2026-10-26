"""Spots a draft reply that says Omi does not know, so code can search before it is sent.

The reply model often answers "I don't know" or "I don't have that info" about something that is in
the user's stored chats, without calling the search tool. A draft like that gets one search over the
real lines; when they answer it, the reply is written again from them.
"""

from __future__ import annotations

import re

# "I don't know" in the ways replies say it, English and Hinglish.
_UNKNOWN = re.compile(
    r"\b(i\s+(do\s*n[o']?t|don'?t)\s+(know|have\s+(that|this|any|much)?\s*(info|information|details?))"
    r"|(no|not\s+sure)\s+(idea|info|information)"
    r"|nahi\s+pata|pata\s+nahi|nahin\s+pata|nahi\s+jaant[ai]|nahi\s+maloom|maloom\s+nahi"
    r"|koi\s+(info|jaankari|idea)\s+nahi"
    r"|mention\s+nahi|nahi\s+(bataya|batay[ai]|kaha|hua\s+mention)"
    r"|(didn'?t|did\s+not|never)\s+(mention|come\s+up|say)"
    r"|could\s*n'?t\s+find|not\s+in\s+(the|your|that)\s+(chat|chats|upload))",
    re.IGNORECASE,
)


def says_unknown(reply: str) -> bool:
    return bool(_UNKNOWN.search(reply or ""))


__all__ = ["says_unknown"]
