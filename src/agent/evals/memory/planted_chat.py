"""A made-up WhatsApp chat between two friends, months long, with running jokes planted in it.

For testing the read (agent.cognition.background.uploads.chat_read): the chat is mostly ordinary
talk that changes every day, and a few things come back again and again the way they do between
real friends. A good read finds those and not the ordinary talk. Everything here is invented.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

ME = "Aman Verma"
THEM = "Riya Shah"

# What a good read should find. phrase -> what it is between them.
PLANTED_JOKES = {
    "paanch minute": "Riya is always 'five minutes' away and arrives an hour later",
    "professor": "Riya's name for Aman when he over-explains",
    "sharma ji": "the neighbour who complains about everything",
    "bottle": "the bottle Aman left in Riya's bag on the first trek, never returned",
}
PLANTED_SUBJECTS = ("sinhagad", "deadline")

_OPENERS = ("kya chal raha hai", "aaj ka din kaisa tha", "office se nikla abhi", "khana kha liya?", "so gayi kya", "uth gaya?", "aaj bahut thak gaya", "kal ka plan bata", "ghar pahunch gayi", "chai pi li?")
_REPLIES = ("haan bas abhi", "nahi yaar abhi tak nahi", "theek hai", "pata nahi dekhte hain", "acha", "hmm sahi hai", "bol na", "abhi busy hu thoda", "haan haan", "kal batati hu")
_TOPICS = ("metro", "barish", "traffic", "manager", "laptop", "maggi", "movie", "cricket", "rent", "gym", "wifi", "auto wala", "canteen", "meeting", "charger", "weekend", "mummy ka call", "bhai ki shaadi", "naya phone", "exam result")
_ABOUT = (
    "ne aaj dimaag kharab kar diya", "ka scene ajeeb hai", "phir se wahi drama", "theek ho gaya finally", "ke bina kaam nahi chalega",
    "pe paisa barbaad", "dekh ke hasi aa gayi", "ka kuch karna padega", "mein phas gaya tha", "wala kissa sunna", "ka update aaya kya",
    "kal se band hai", "ne bachaa liya", "pe bharosa mat karna", "kitna mehenga ho gaya", "ab adat ban gayi", "ki wajah se late hua",
    "ko bhool hi gayi thi", "sabse bekaar cheez hai", "ke liye chutti chahiye", "lagta hai kharab hai", "ne mood bana diya",
    "ko ignore kar", "ka time ho gaya",
)
_LAUGHS = ("hahaha", "😂😂", "lol", "hahahaha mar gayi", "😂", "haha stop")


def planted_export(seed: int = 7, days: int = 170) -> str:
    """The chat as WhatsApp's "Export chat" text. The same seed gives the same chat."""
    rng = random.Random(seed)
    start = datetime(2026, 4, 2, 9, 0)
    lines: list[str] = []

    def say(at: datetime, who: str, text: str) -> None:
        lines.append(f"{at:%d/%m/%Y}, {at.hour % 12 or 12}:{at:%M} {'am' if at.hour < 12 else 'pm'} - {who}: {text}")

    say(start, THEM, "hi, is this Aman from the Rajmachi trek? tumhara bottle mere bag mein reh gaya")
    say(start + timedelta(minutes=3), ME, "arre haan! rakh lo, next trek pe le lunga")
    for day in range(1, days):
        if rng.random() < 0.22:
            continue  # a quiet day
        at = start + timedelta(days=day, hours=rng.choice((0, 9, 10, 11, 12)), minutes=rng.randrange(60))
        # Riya starts more often; Aman answers slowly.
        first, second = (THEM, ME) if rng.random() < 0.65 else (ME, THEM)
        say(at, first, rng.choice(_OPENERS))
        at += timedelta(minutes=rng.randrange(2, 9) if second == THEM else rng.randrange(40, 180))
        say(at, second, rng.choice(_REPLIES))
        for _ in range(rng.randrange(1, 4)):
            at += timedelta(minutes=rng.randrange(6, 30))
            who = rng.choice((ME, THEM))
            say(at, who, f"{rng.choice(_TOPICS)} {rng.choice(_ABOUT)}")
            if rng.random() < 0.3:
                at += timedelta(minutes=rng.randrange(6, 12))
                say(at, THEM if who == ME else ME, rng.choice(_REPLIES))
        roll = rng.random()
        at += timedelta(minutes=rng.randrange(8, 25))
        if roll < 0.11:
            say(at, THEM, "bas paanch minute mein pahunch rahi hu")
            say(at + timedelta(minutes=7), ME, "tera paanch minute matlab ek ghanta, main chai order kar raha hu")
            say(at + timedelta(minutes=14), THEM, rng.choice(_LAUGHS))
        elif roll < 0.21:
            say(at, ME, f"dekh technically {rng.choice(_TOPICS)} ka poora system aise kaam karta hai, pehle samajh")
            say(at + timedelta(minutes=6), THEM, "ok professor, lecture band kar")
            say(at + timedelta(minutes=13), ME, rng.choice(_LAUGHS))
        elif roll < 0.29:
            say(at, ME, f"sharma ji ne aaj {rng.choice(_TOPICS)} pe complaint kar di society group mein")
            say(at + timedelta(minutes=6), THEM, rng.choice(_LAUGHS) + " sharma ji is undefeated")
        elif roll < 0.35:
            say(at, THEM, "aur mera bag abhi bhi tumhara bottle dho raha hai, kab loge")
            say(at + timedelta(minutes=120), ME, "bottle ab tumhara hi hai, adopt kar lo")
            say(at + timedelta(minutes=127), THEM, rng.choice(_LAUGHS))
        elif roll < 0.43:
            say(at, THEM, "is sunday sinhagad chalein? subah 5 baje")
            say(at + timedelta(minutes=95), ME, rng.choice(("deadline hai yaar, next sunday pakka", "sinhagad pakka, bas deadline nikal jaye")))
        elif roll < 0.47:
            say(at, THEM, "tum reply kal karoge ya parso? subah se wait kar rahi hu")
            say(at + timedelta(minutes=200), ME, "sorry yaar meeting mein tha")
    return "\n".join(lines)


__all__ = ["ME", "PLANTED_JOKES", "PLANTED_SUBJECTS", "THEM", "planted_export"]
