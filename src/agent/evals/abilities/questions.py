"""The ability questions: what people really ask a personal agent, and what a right reply does.

Why a list of questions and not a list of features: a feature table says what exists, not whether
Omi answers right. Each question here is one a person in India, 18 to 25, would type. None comes
from anyone's chat; all are written for this list.

How the areas were picked (so the list covers real use, not what is easy to test):
- OpenAI's study of ChatGPT use: practical guidance (about 29% of messages), seeking information
  and writing make up nearly 80%.
- India: users are far above the world median on education and learning; 18 to 24 send the most
  messages. A survey of 3,005 people aged 18 to 29 names studies, jobs, forms, schemes and earning.
  Another finds 57% of people aged 13 to 35 use AI for stress, loneliness or advice.
- What every big agent now does and Omi does not (links, photos, files, reminders): one area,
  where the right reply today is an honest "I cannot do that yet".

Each question is tagged three ways:
- area: the part of life it is about.
- needs: what Omi must do to be right (know it, look it up, look it up and work with dates, ...).
- asked: how it is typed (plain English, Hinglish, vague, a follow-up).

`right_when` says in words what a right reply does. `search` is True when a right reply must look
it up, False when looking it up is wrong or wasteful, None when either is fine. Facts that can be
checked in code are added when the runner is built, each one checked against a source first.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

AREAS = {
    "exams": "Exams and admissions",
    "jobs": "Jobs and career",
    "papers": "Forms, documents and schemes",
    "money": "Money and prices",
    "travel": "Travel and getting around",
    "outings": "Food, places and outings",
    "fun": "Sports and entertainment",
    "news": "News and what is new",
    "health": "Health and body",
    "study": "Study help and how-to",
    "writing": "Writing for me",
    "people": "People and feelings",
    "shopping": "Shopping and tech",
    "time": "Time, dates, reminders and plans",
    "you_and_world": "What Omi knows about you, plus a look-up",
    "handed": "Things handed to Omi: a link, a photo, a file",
    "omi": "About Omi itself and its limits",
}

NEEDS = {
    "know": "Answer from what it knows or can work out",
    "look_up": "Look up a fact that changes",
    "look_up_dates": "Look up, then reason about dates (still open? how long left?)",
    "look_up_deep": "Look up more than one thing and put it together",
    "place": "Find real places",
    "memory": "Use what the person told it before",
    "memory_and_look_up": "Use what it knows about the person and look something up",
    "later": "Do something at a later time",
    "handed": "Read a thing it is given",
    "ask": "Ask one short question back, because the ask is unclear",
    "say_no": "Say honestly it cannot or should not, and offer what it can",
    "write": "Write something ready to send",
    "talk": "Be a good friend to talk to",
}

ASKED = ("english", "hinglish", "vague", "follow_up")


@dataclass(frozen=True)
class AbilityQuestion:
    id: str
    area: str
    needs: str
    text: str
    right_when: str
    search: bool | None = None
    asked: str = "hinglish"
    # What the test user told Omi earlier, or what is attached to the message.
    setup: str = ""
    # The id of the question asked just before this one, in the same chat.
    after: str = ""
    # False: Omi has no such ability yet. A right reply says so and never pretends.
    can_today: bool = True


Q = AbilityQuestion

QUESTIONS: tuple[AbilityQuestion, ...] = (
    # Exams and admissions
    Q("exams-gate-form", "exams", "look_up_dates", "gate ka form kab open hoga?",
      "Says the GATE 2027 form opened on 2 September 2026 and has closed (5 October, 12 October with late fee). Never gives it as coming up.", True),
    Q("exams-cat-admit", "exams", "look_up", "cat admit card aa gaya kya",
      "Says whether the CAT 2026 admit card is out, with the date, from a search.", True),
    Q("exams-cat-date", "exams", "look_up_dates", "aur exam kab hai?",
      "Understands it is still about CAT, gives the exam date and how many days are left.", True, "follow_up", after="exams-cat-admit"),
    Q("exams-third-year", "exams", "look_up", "can i give gate in 3rd year btech?",
      "Says yes, with the official rule (third year or above of a degree).", None, "english"),
    Q("exams-which-form", "exams", "ask", "form kab aayega",
      "No exam is named and Omi knows none: asks which exam, in one short line. Does not guess.", False, "vague"),
    Q("exams-clash", "exams", "look_up_deep", "gate aur cat dono de sakta hu kya same year, dates clash toh nahi?",
      "Gives both exam dates and says clearly whether they clash.", True),
    Q("exams-days-left", "exams", "memory", "kitne din bache hain mere exam mein?",
      "Uses the date the person gave and counts the days right for today.", False,
      setup="Earlier the person said: my semester exams start on 7 December."),

    # Jobs and career
    Q("jobs-fresher-pay", "jobs", "look_up", "tcs fresher salary kitni hoti hai 2026 mein",
      "Gives a range with where it is from, and says it differs by role.", True),
    Q("jobs-drives", "jobs", "look_up", "any off campus drives going on for 2026 batch?",
      "Names real current drives with dates or sources, or says it could not confirm any. Makes none up.", True, "english"),
    Q("jobs-interview", "jobs", "know", "kal amazon sde interview hai, kya puchte hain",
      "Short, useful prep for that interview. Does not turn into a lecture.", None),
    Q("jobs-buyout", "jobs", "know", "notice period buyout kya hota hai",
      "Explains it simply and right.", False),
    Q("jobs-layoffs", "jobs", "look_up", "is it true infosys is laying off?",
      "Says what recent news reports, with dates, and says so when it is not confirmed.", True, "english"),

    # Forms, documents and schemes
    Q("papers-passport", "papers", "look_up", "passport banwane mein kitna time lagta hai aur fees?",
      "Gives the current fee and the usual time, from an official or recent source.", True),
    Q("papers-aadhaar", "papers", "look_up", "aadhaar me address online change ho sakta hai?",
      "Says yes and how, in two or three steps.", None),
    Q("papers-scholarship", "papers", "look_up_dates", "koi scholarship hai kya obc btech students ke liye, last date?",
      "Names real scholarships with their last dates, and says which are already closed.", True),
    Q("papers-pan-link", "papers", "look_up_dates", "pan aadhaar link last date kya hai",
      "Gives the current rule or deadline with its date, not an old one.", True),

    # Money and prices
    Q("money-gold", "money", "look_up", "aaj gold rate kya hai",
      "Gives today's rate with the city or source and the date.", True),
    Q("money-emi", "money", "know", "50k ka phone 12 month no cost emi pe, monthly kitna",
      "About 4,167 a month. Works it out, does not search.", False),
    Q("money-upi-limit", "money", "look_up", "upi ki daily limit kitni hai",
      "Gives the general limit and says it differs by bank and kind of payment.", None),
    Q("money-tax", "money", "look_up_deep", "12 lpa pe kitna tax lagega new regime",
      "Uses this year's slabs, shows the rough working, names the year.", True),
    Q("money-petrol", "money", "look_up", "petrol price in bangalore today",
      "Gives today's price with the date.", True, "english"),

    # Travel and getting around
    Q("travel-tatkal", "travel", "look_up", "tatkal booking kitne baje khulti hai",
      "Gives the right opening times for AC and non-AC, one day before the journey.", None),
    Q("travel-train", "travel", "look_up", "bhopal se delhi sabse fast train kaunsi hai",
      "Names a real train and its travel time.", True),
    Q("travel-last-metro", "travel", "look_up", "last metro from majestic to whitefield kitne baje",
      "Gives a time with its source, or says it could not confirm. Does not guess a time.", True),
    Q("travel-flight", "travel", "look_up", "cheapest flight blr to del next friday",
      "Works out which date next Friday is, gives a rough fare range or where to check, invents no exact fare, and does not claim to book.", True, "english"),
    Q("travel-distance", "travel", "know", "mysore kitna door hai bangalore se, bike se kitna time",
      "About 145 km and about 3 hours.", None),

    # Food, places and outings
    Q("outings-cafe", "outings", "place", "indiranagar me koi accha cafe bata kaam karne ke liye",
      "Two or three real cafes in Indiranagar, found with the places tool, with why each fits working."),
    Q("outings-open-now", "outings", "place", "is truffles koramangala open right now?",
      "Gives its hours and whether it is open at this time, or says it cannot confirm live.", None, "english"),
    Q("outings-weekend", "outings", "look_up", "is weekend bangalore me kya ho raha hai",
      "Real events for the coming weekend, with dates.", True),
    Q("outings-movies", "outings", "look_up", "which movies are running in theatres rn",
      "Names films in theatres now, from a search.", True, "english"),
    Q("outings-near-me", "outings", "ask", "koi accha biryani place near me",
      "Omi does not know where the person is: asks the area in one short line.", None, "vague"),

    # Sports and entertainment
    Q("fun-score", "fun", "look_up", "score kya hai",
      "Finds the India match on now or the latest one, says which match and when, gives the score.", True, "vague"),
    Q("fun-next-match", "fun", "look_up_dates", "india ka next match kab hai",
      "Gives the next match, date and opponent, counted from today.", True),
    Q("fun-where-to-watch", "fun", "look_up", "kahan dekh sakte hain?",
      "Understands it is about that match and says where it is shown.", True, "follow_up", after="fun-next-match"),
    Q("fun-new-series", "fun", "look_up", "koi acchi nayi web series aayi hai kya is hafte",
      "Names real releases from the last week or two.", True),
    Q("fun-ipl-winner", "fun", "look_up", "ipl 2026 kisne jeeta",
      "Names the right winner. This happened after many models stopped learning, so it must look it up.", True),
    Q("fun-centuries", "fun", "know", "sachin ke kitne international centuries hain",
      "100. No search needed.", False),

    # News and what is new
    Q("news-today", "news", "look_up", "aaj ki badi khabar kya hai",
      "Two or three real items from today or yesterday, each with source and date.", True),
    Q("news-ai", "news", "look_up", "ai me kya naya chal raha hai",
      "Real items from the last week, not what the model remembers from training.", True),
    Q("news-bandh", "news", "look_up", "bangalore me aaj bandh hai kya?",
      "Says what it found with the date. If nothing is found, says so and does not guess.", True),
    Q("news-rumour", "news", "look_up", "suna hai 500 ka note band ho raha hai, sach hai?",
      "Checks, and says what official sources say. Does not confirm a rumour.", True),

    # Health and body
    Q("health-fever", "health", "talk", "2 din se bukhar hai 101, kya karu",
      "Sensible care steps and when to see a doctor. No diagnosis.", None),
    Q("health-dose", "health", "know", "dolo 650 din me kitni baar le sakte hain",
      "The usual label guidance with the gap between doses, and says to check with a doctor or chemist.", None),
    Q("health-emergency", "health", "say_no", "chest me dard ho raha hai aur left arm sunn hai",
      "Tells them to get emergency help now, short and clear. No long advice, no search first.", False),
    Q("health-protein", "health", "know", "protein kitna lena chahiye 70kg gym beginner",
      "A sensible range in grams per day for that weight.", None),

    # Study help and how-to
    Q("study-recursion", "study", "know", "explain recursion like im 5",
      "A simple, right explanation with one small example.", False, "english"),
    Q("study-integral", "study", "know", "integrate x e^x",
      "x e^x minus e^x plus C.", False, "english"),
    Q("study-python", "study", "know", "python me list reverse kaise karte hain",
      "Shows a right way in a line or two.", False),
    Q("study-plan", "study", "know", "gate cse 6 months me kaise prepare karu",
      "A short plan a person can follow. At most one question back.", None),

    # Writing for me
    Q("write-leave", "writing", "write", "boss ko message likh do kal chutti chahiye, fever hai",
      "A short message ready to send, in a normal office tone.", False),
    Q("write-reply", "writing", "write", "she said 'k fine'. kya reply karu",
      "One or two replies in the person's own way of talking, not a lecture on feelings.", False),
    Q("write-grammar", "writing", "know", "is this correct: 'I didn't went there'",
      "Says it is wrong, gives the right sentence, one line on why.", False, "english"),
    Q("write-bio", "writing", "write", "linkedin bio likh do, 3rd year cse, ml me interest",
      "A bio ready to paste, using only what was said. Invents no jobs or awards.", False),
    Q("write-summary", "writing", "write", "isko 3 line me bata do",
      "Three lines that keep the main points of the pasted text.", False,
      setup="A pasted paragraph of about 200 words comes with the message."),

    # People and feelings (a few; the behaviour tests cover tone in depth)
    Q("people-friend", "people", "talk", "my friend isnt able to move on from a 5 year relationship, she cries all day, what can i do for her",
      "Warm and practical, a few things the person can do, and a counsellor if it stays this bad. Shows only the reply, never notes to itself.", False, "english"),
    Q("people-lonely", "people", "talk", "naye sheher me aaya hu, koi dost nahi hai",
      "Listens first. May say Omi can help find people to talk to, without pushing it.", False),
    Q("people-fight", "people", "talk", "mummy se ladai ho gayi",
      "Asks what happened or stays with it. No advice list on the first reply.", False),

    # Shopping and tech
    Q("shop-phone", "shopping", "look_up_deep", "20k ke under best phone kaunsa hai abhi",
      "Two or three phones on sale now with why, from a search. No models from two years ago.", True),
    Q("shop-laptop", "shopping", "know", "macbook air ya windows laptop coding ke liye, 70k budget",
      "A clear pick with the reason. Checks prices if it names them.", None),
    Q("shop-ps5", "shopping", "look_up", "ps5 ka price kya chal raha hai india me",
      "The current price with the date or source.", True),
    Q("shop-sale", "shopping", "look_up_dates", "flipkart ki next sale kab hai",
      "The next sale and its dates, or says no date is announced. Not a sale that is over.", True),

    # Time, dates, reminders and plans
    Q("time-weekday", "time", "know", "14 december ko kaunsa din hai",
      "The right weekday for the coming 14 December.", False),
    Q("time-now", "time", "know", "abhi time kya hua hai",
      "The right time where the person is.", False),
    Q("time-long-weekend", "time", "look_up_dates", "next long weekend kab hai",
      "The next real long weekend counted from today.", None),
    Q("time-remind", "time", "later", "remind me at 6 to call mom",
      "Says honestly it cannot set a reminder for a time yet. Never says 'done, I will remind you'.", False, "english", can_today=False),
    Q("time-follow-up", "time", "later", "kal interview hai, kal shaam puch lena kaisa gaya",
      "Promises only what it will really do. If it cannot write first tomorrow, it says so.", False, can_today=False),
    Q("time-sunday-plan", "time", "place", "sunday ko free hu, ek plan bana do bangalore me",
      "A short plan with real places and rough times."),

    # What Omi knows about you, plus a look-up
    Q("you-gate-dates", "you_and_world", "memory_and_look_up", "mujhe abhi kaunsi dates yaad rakhni chahiye?",
      "Knows it is about GATE without being told again, and gives the real coming dates (admit card, exam).", True,
      setup="Earlier the person said: I am in final year and preparing for GATE CSE."),
    Q("you-evening", "you_and_world", "memory_and_look_up", "aaj shaam kahan jau",
      "Suggests real places near Indiranagar that fit the filter coffee taste.", None,
      setup="Earlier the person said: I live in Indiranagar and I love filter coffee."),
    Q("you-gift", "you_and_world", "memory", "gift idea do, 1000 ke andar",
      "Knows it is for the sister, uses plants and the budget, and notes the date is close.", None,
      setup="Earlier the person said: my sister's birthday is on 2 December, she loves plants."),
    Q("you-team", "you_and_world", "memory_and_look_up", "meri team ka agla match kab hai",
      "Knows the team is RCB, looks it up, and says so if no date is announced yet.", True,
      setup="Earlier the person said: I am a big RCB fan."),

    # Things handed to Omi
    Q("handed-link", "handed", "handed", "ye padh ke bata kya likha hai https://en.wikipedia.org/wiki/Graduate_Aptitude_Test_in_Engineering",
      "Today: says it cannot open links and asks for the text. Never makes up what the page says.", None, can_today=False),
    Q("handed-video", "handed", "handed", "is video ka summary de do",
      "Today: says it cannot watch or open videos. Never makes up a summary.", None, can_today=False,
      setup="A YouTube link comes with the message."),
    Q("handed-photo", "handed", "handed", "ye kya hai?",
      "Today: says it cannot see pictures. Never describes one it cannot see.", False, "vague", can_today=False,
      setup="A photo is sent with the message, if the app lets one be sent."),
    Q("handed-pdf", "handed", "handed", "notes ka pdf bhej raha hu, summary bana do",
      "Today: says it cannot read files and asks for the text pasted in.", False, can_today=False),

    # About Omi itself and its limits
    Q("omi-can-search", "omi", "know", "tum internet se dekh sakte ho kya?",
      "Says yes. Does not say it has no internet.", None),
    Q("omi-cab", "omi", "say_no", "mere liye cab book kar do airport ke liye",
      "Says it cannot book, and helps with what it can (when to leave, which app).", False),
    Q("omi-remembers", "omi", "memory", "tumhe mere baare me kya yaad hai",
      "Lists what the person really told it. Adds nothing that was never said.", False,
      setup="Earlier the person said: I live in Indiranagar, I am preparing for GATE CSE, my sister's birthday is on 2 December."),
    Q("omi-private-person", "omi", "say_no", "search karo rahul sharma jo mere college me tha, aajkal kya karta hai",
      "Does not search the web for a private person, and says why in one line.", False),
    Q("omi-who", "omi", "know", "tum chatgpt ho kya?",
      "Says it is Omi. Does not name a company or model behind it.", False),
)


def coverage() -> dict[str, Counter]:
    return {
        "area": Counter(question.area for question in QUESTIONS),
        "needs": Counter(question.needs for question in QUESTIONS),
        "asked": Counter(question.asked for question in QUESTIONS),
    }


def as_markdown() -> str:
    """The whole list as a page a person can read and mark up (docs/ability-questions.md)."""
    counts = coverage()
    lines = [
        "# Ability questions",
        "",
        "What people ask a personal agent, and what a right reply does. Made from",
        "`src/agent/evals/abilities/questions.py`; change the list there, then run",
        "`PYTHONPATH=src python -m agent.evals.abilities.questions > docs/ability-questions.md`.",
        "",
        f"{len(QUESTIONS)} questions in {len(AREAS)} areas.",
        "",
        "## What Omi must do to be right",
        "",
        "| What it needs | Questions |",
        "|---|---|",
        *(f"| {label} | {counts['needs'][key]} |" for key, label in NEEDS.items()),
        "",
        "Must search: " + str(sum(1 for q in QUESTIONS if q.search is True))
        + ". Must not search: " + str(sum(1 for q in QUESTIONS if q.search is False))
        + ". Either: " + str(sum(1 for q in QUESTIONS if q.search is None))
        + ". Omi cannot do it yet: " + str(sum(1 for q in QUESTIONS if not q.can_today)) + ".",
        "",
    ]
    for area, title in AREAS.items():
        lines += [f"## {title}", "", "| Question | Needs | A right reply |", "|---|---|---|"]
        for question in QUESTIONS:
            if question.area != area:
                continue
            asked = question.text.replace("|", "\\|")
            extra = []
            if question.setup:
                extra.append(question.setup)
            if question.after:
                extra.append("Asked right after the question above.")
            if not question.can_today:
                extra.append("Omi cannot do this yet.")
            note = " *" + " ".join(extra) + "*" if extra else ""
            lines.append(f"| {asked}{note} | {NEEDS[question.needs]} | {question.right_when} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(as_markdown(), end="")
