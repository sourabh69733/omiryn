from __future__ import annotations


def agent_persona_for_interest(interested_in: str) -> dict[str, str]:
    if interested_in == "women":
        return {"name": "Annie", "presentation": "girl/woman companion"}
    if interested_in == "men":
        return {"name": "Arjun", "presentation": "boy/man companion"}
    return {"name": "Omi", "presentation": "warm neutral companion"}
