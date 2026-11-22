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

Career is the centre of the list, and it is written stage by stage, because a second-year student,
someone hunting a first job and someone one year into a job ask different things:
- Surveys of Indian students and job seekers in 2026: 72% say even beginner roles ask for
  experience, 61% rarely hear back after applying, only 20% had a paid internship, 58% already
  paid for a course outside college, and over 90% would take lower pay for better learning.
- Each stage gets the same spread on purpose: something to look up, a decision that needs a clear
  view, something to write, a hard moment to talk through, and one that uses what Omi knows.

Each question is tagged four ways:
- who: the stage of life of the person asking.
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

WHO = {
    "student": "In college, first to third year (about 18 to 21)",
    "finishing": "Final year or just out, after a first job or more study (about 21 to 23)",
    "working": "In the first few years of a job (about 22 to 27)",
    "aspirant": "Preparing full time for a government or entrance exam",
    "anyone": "Anyone",
}

AREAS = {
    "career": "Career",
    "exams": "Exams and admissions",
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
    "decide": "Help decide, with a clear view and the reason",
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
    # What the person told Omi earlier, in their own words. The runner puts it in the chat first.
    earlier: str = ""
    # Text the person pastes along with the question.
    pasted: str = ""
    # A note on anything else that comes with the message.
    setup: str = ""
    # False: the test cannot send this at all (a photo), so it is listed but not run.
    runnable: bool = True
    # The id of the question asked just before this one, in the same chat.
    after: str = ""
    # False: Omi has no such ability yet. A right reply says so and never pretends.
    can_today: bool = True
    who: str = "anyone"


Q = AbilityQuestion

# Written for this list. The three points a summary must keep: the hostel moved the mess timing,
# the reason was the new exam schedule, and students can ask for a packed dinner.
PASTED_PARAGRAPH = (
    "Notice for all hostel residents. From Monday the mess will serve dinner from 7 pm to 9 pm, not 8 pm to "
    "10 pm as before. The change is because the end-semester exams now start at 8 am, and the warden's office "
    "wants students to sleep earlier in exam weeks. Breakfast moves to 6.30 am for the same reason, and lunch "
    "stays as it is. Students who have a lab or a class that runs past 8.30 pm can ask for a packed dinner. To "
    "do that, write your name and room number in the register at the mess counter before 5 pm on the same day. "
    "Packed dinners are kept at the counter until 10.30 pm and not after that. The old timings come back once "
    "the exams are over, on the date the academic office announces."
)

QUESTIONS: tuple[AbilityQuestion, ...] = (
    # Exams and admissions
    Q("exams-gate-form", "exams", "look_up_dates", "gate ka form kab open hoga?",
      "Says the GATE 2027 form opened on 2 September 2026 and has closed (5 October, 12 October with late fee). Never gives it as coming up.", True, who="finishing"),
    Q("exams-cat-admit", "exams", "look_up", "cat admit card aa gaya kya",
      "Says whether the CAT 2026 admit card is out, with the date, from a search.", True, who="finishing"),
    Q("exams-cat-date", "exams", "look_up_dates", "aur exam kab hai?",
      "Understands it is still about CAT, gives the exam date and how many days are left.", True, "follow_up", after="exams-cat-admit", who="finishing"),
    Q("exams-third-year", "exams", "look_up", "can i give gate in 3rd year btech?",
      "Says yes, with the official rule (third year or above of a degree).", None, "english", who="student"),
    Q("exams-which-form", "exams", "ask", "form kab aayega",
      "No exam is named and Omi knows none: asks which exam, in one short line. Does not guess.", False, "vague"),
    Q("exams-clash", "exams", "look_up_deep", "gate aur cat dono de sakta hu kya same year, dates clash toh nahi?",
      "Gives both exam dates and says clearly whether they clash.", True, who="finishing"),
    Q("exams-days-left", "exams", "memory", "kitne din bache hain mere exam mein?",
      "Uses the date the person gave and counts the days right for today.", False,
      earlier="My semester exams start on 7 December.", who="student"),

    # Career: in college, first to third year
    Q("career-s-internship-how", "career", "know", "2nd year me hu, internship kaise milegi",
      "Three or four steps a second-year student can start this week. Not a list of ten general tips.", None, who="student"),
    Q("career-s-internship-open", "career", "look_up_dates", "summer 2027 internship ke liye abhi kaunsi companies ke form open hain",
      "Real programmes that are open now, each with its last date. Says which are already closed.", True, who="student"),
    Q("career-s-dsa-or-dev", "career", "decide", "dsa karu ya development, placement ke liye kya zyada kaam aata hai",
      "Gives a clear view and why. May ask the year or branch once. Does not end on 'both are important'.", False, who="student"),
    Q("career-s-low-cgpa", "career", "know", "cgpa 6.8 hai, placement me dikkat hogi?",
      "Honest: some companies have a cutoff. Then what still works at 6.8. No false comfort.", None, who="student"),
    Q("career-s-branch", "career", "know", "mechanical se hu, software job mil sakti hai?",
      "Says yes and how people do it, in a few lines.", False, who="student"),
    Q("career-s-paid-course", "career", "decide", "ek 40k ka data science course hai, lena chahiye kya",
      "A clear view. Asks what it is for or names free ways to learn the same. Does not sell the course.", None, who="student"),
    Q("career-s-resume", "career", "write", "resume me kya likhu, koi experience nahi hai",
      "Says what a student with no job can put, and offers to draft it. Invents no experience.", False, who="student"),
    Q("career-s-gsoc", "career", "look_up_dates", "gsoc 2027 kab start hoga",
      "The real timeline, or says it is not announced yet. Not last year's dates as this year's.", True, who="student"),
    Q("career-s-prof-mail", "career", "write", "ek professor ko research internship ke liye mail likh do",
      "A short mail ready to send, with blanks only where it needs the person's own details.", False, who="student"),
    Q("career-s-left-out", "career", "talk", "sabko internship mil gayi, mujhe nahi mili",
      "Stays with the feeling first. At most one small next step. No advice list.", False, who="student"),
    Q("career-s-this-sem", "career", "memory", "is semester me career ke liye kya karu",
      "Uses the branch, the interest in design and the missing internship. An answer only this person would get.", None, who="student",
      earlier="I am in second year ECE, I like UI design, I have no internship yet."),

    # Career: final year or just out
    Q("career-f-drives", "career", "look_up", "any off campus drives going on for 2026 batch?",
      "Names real current drives with dates or sources, or says it could not confirm any. Makes none up.", True, "english", who="finishing"),
    Q("career-f-fresher-pay", "career", "look_up", "tcs fresher salary kitni hoti hai 2026 mein",
      "Gives a range with where it is from, and says it differs by role.", True, who="finishing"),
    Q("career-f-nqt", "career", "look_up_dates", "tcs nqt ka next exam kab hai",
      "The next real date and the last date to register, or says it is not announced.", True, who="finishing"),
    Q("career-f-two-offers", "career", "decide", "2 offer hain: 6 lpa service company bangalore, 4.5 lpa startup pune jahan kaam accha hai. kaunsa lu",
      "Leans one way, says why, and says what would change the answer. At most one question back.", False, who="finishing"),
    Q("career-f-mtech-or-job", "career", "decide", "mtech karu ya job",
      "Asks the one thing it needs, or gives a view with the reason. Not only 'it depends'.", False, "vague", who="finishing"),
    Q("career-f-gre", "career", "look_up", "ms ke liye gre zaruri hai kya fall 2027 ke liye",
      "Says what universities ask now, that it differs by university, from a search.", True, who="finishing"),
    Q("career-f-not-placed", "career", "talk", "placement nahi hua, sab dost place ho gaye",
      "Stays with it first. Then one real next step. No pep talk.", False, who="finishing"),
    Q("career-f-no-reply", "career", "talk", "50 jagah apply kiya, kahin se reply nahi aaya",
      "Says this is common, then finds what to fix: asks how they apply, or gives two changes.", False, who="finishing"),
    Q("career-f-experience", "career", "know", "fresher role me bhi 2 saal experience maang rahe hain, kya karu",
      "Practical ways around it: apply anyway, what counts as experience. Short.", False, who="finishing"),
    Q("career-f-interview", "career", "know", "kal amazon sde interview hai, kya puchte hain",
      "Short, useful prep for that interview. Does not turn into a lecture.", None, who="finishing"),
    Q("career-f-expected-pay", "career", "know", "interview me expected salary puche toh kya bolu, fresher hu",
      "A line the person can say, and how to pick the number.", False, who="finishing"),
    Q("career-f-bond", "career", "decide", "offer letter me 2 saal ka bond hai 2 lakh ka, sign karu?",
      "Explains what the bond means, what to check before signing, and gives a view. Does not claim to be a lawyer.", None, who="finishing"),
    Q("career-f-hr-mail", "career", "write", "hr ko follow up mail likh do, interview ko 1 hafta ho gaya",
      "A short, polite mail ready to send.", False, who="finishing"),
    Q("career-f-referral", "career", "write", "linkedin pe referral maangne ka message likh do",
      "A short message that does not beg, with a blank for the role.", False, who="finishing"),
    Q("career-f-openings", "career", "memory_and_look_up", "mere liye koi opening dekh ke batao",
      "Looks for backend fresher roles that fit, without asking again what the person wants.", True, who="finishing",
      earlier="I am in final year CSE, 7.4 CGPA, I want backend roles, I am in Bhopal."),

    # Career: first few years of a job
    Q("career-w-buyout", "career", "know", "notice period buyout kya hota hai",
      "Explains it simply and right.", False, who="working"),
    Q("career-w-layoffs", "career", "look_up", "is it true infosys is laying off?",
      "Says what recent news reports, with dates, and says so when it is not confirmed.", True, "english", who="working"),
    Q("career-w-hike", "career", "look_up", "switch pe 30% hike normal hai kya abhi",
      "What recent reports say for this year, with the source. Not a number from memory.", True, who="working"),
    Q("career-w-pf", "career", "look_up", "job chhodne ke baad pf kaise nikalte hain",
      "The steps under the current rules, short.", None, who="working"),
    Q("career-w-switch", "career", "decide", "1 saal ho gaya company me, switch karu ya ruku",
      "Asks the one thing that matters, or gives a view with the reason.", False, who="working"),
    Q("career-w-mba", "career", "decide", "2 saal job ke baad mba karna worth hai kya",
      "A clear view with the reason, and what it depends on in one line.", False, who="working"),
    Q("career-w-moonlight", "career", "know", "job ke saath freelancing kar sakta hu kya",
      "Says it depends on the contract and what to check. Does not just say yes.", False, who="working"),
    Q("career-w-no-hike", "career", "talk", "appraisal me hike nahi mila, manager se kaise baat karu",
      "How to raise it, and a line or two the person can say.", False, who="working"),
    Q("career-w-weekend", "career", "talk", "manager weekend pe bhi kaam karwata hai, mana kaise karu",
      "A way to say no that keeps the job safe, with words to use.", False, who="working"),
    Q("career-w-tired", "career", "talk", "roz office jaane ka mann nahi karta",
      "Asks what is going on. No productivity tips on the first reply.", False, who="working"),
    Q("career-w-resign", "career", "write", "resignation mail likh do, 2 month notice hai",
      "A short mail ready to send.", False, who="working"),
    Q("career-w-negotiate", "career", "write", "offer aaya hai 9 lpa, 11 kaise maangu, mail likh do",
      "A mail that asks for 11 with a reason, ready to send.", False, who="working"),
    Q("career-w-next-skill", "career", "memory", "agle 3 mahine me kya seekhu",
      "Uses the testing job and the wish to move to development. A plan only this person would get.", None, who="working",
      earlier="I have been a manual tester at a service company for 1.5 years and I want to move to development."),

    # Career: preparing full time for an exam
    Q("career-a-attempts", "career", "talk", "3 attempt ho gaye, clear nahi hua, ab kya karu",
      "Takes it seriously, asks or reflects first. No quick fix.", False, who="aspirant"),
    Q("career-a-backup", "career", "decide", "upsc ke saath koi backup rakhna chahiye kya",
      "A clear view with the reason.", False, who="aspirant"),

    Q("exams-a-ssc", "exams", "look_up_dates", "ssc cgl tier 1 kab hai",
      "The real date for the current cycle and how far away it is.", True, who="aspirant"),
    Q("exams-a-upsc", "exams", "look_up_dates", "upsc prelims 2027 kab hai",
      "The date from the official calendar, or says it is not out yet.", True, who="aspirant"),
    Q("exams-a-age", "exams", "look_up", "bank po ke liye age limit kya hai",
      "The age limit and the usual relaxations, with the source.", None, who="aspirant"),
    Q("exams-a-current", "exams", "look_up", "aaj ke current affairs bata do exam ke liye",
      "Real items from today or yesterday, short, the kind an exam asks.", True, who="aspirant"),

    # Forms, documents and schemes
    Q("papers-passport", "papers", "look_up", "passport banwane mein kitna time lagta hai aur fees?",
      "Gives the current fee and the usual time, from an official or recent source.", True),
    Q("papers-aadhaar", "papers", "look_up", "aadhaar me address online change ho sakta hai?",
      "Says yes and how, in two or three steps.", None),
    Q("papers-scholarship", "papers", "look_up_dates", "koi scholarship hai kya obc btech students ke liye, last date?",
      "Names real scholarships with their last dates, and says which are already closed.", True, who="student"),
    Q("papers-itr", "papers", "look_up_dates", "itr bharne ki last date kya hai",
      "The date for this year, and whether it has passed.", True, who="working"),
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
      "Uses this year's slabs, shows the rough working, names the year.", True, who="working"),
    Q("money-petrol", "money", "look_up", "petrol price in bangalore today",
      "Gives today's price with the date.", True, "english"),

    Q("money-allowance", "money", "know", "ghar se mahine ka 8000 milta hai, kaise manage karu",
      "A simple split for a student budget. Short.", False, who="student"),
    Q("money-first-salary", "money", "know", "pehli salary aayi hai, kahan lagau paise",
      "General first steps like an emergency fund. Pushes no product and says it is not personal investment advice.", None, who="working"),
    Q("money-rent", "money", "look_up", "hsr layout me 1bhk ka rent kitna chal raha hai",
      "A current range with where it is from.", True, who="working"),

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
      "A short plan a person can follow. At most one question back.", None, who="finishing"),

    # Writing for me
    Q("write-leave", "writing", "write", "boss ko message likh do kal chutti chahiye, fever hai",
      "A short message ready to send, in a normal office tone.", False, who="working"),
    Q("write-reply", "writing", "write", "she said 'k fine'. kya reply karu",
      "One or two replies in the person's own way of talking, not a lecture on feelings.", False),
    Q("write-grammar", "writing", "know", "is this correct: 'I didn't went there'",
      "Says it is wrong, gives the right sentence, one line on why.", False, "english"),
    Q("write-bio", "writing", "write", "linkedin bio likh do, 3rd year cse, ml me interest",
      "A bio ready to paste, using only what was said. Invents no jobs or awards.", False, who="student"),
    Q("write-summary", "writing", "write", "isko 3 line me bata do",
      "Three lines that keep the main points of the pasted text.", False,
      pasted=PASTED_PARAGRAPH),

    # People and feelings (a few; the behaviour tests cover tone in depth)
    Q("people-friend", "people", "talk", "my friend isnt able to move on from a 5 year relationship, she cries all day, what can i do for her",
      "Warm and practical, a few things the person can do, and a counsellor if it stays this bad. Shows only the reply, never notes to itself.", False, "english"),
    Q("people-lonely", "people", "talk", "naye sheher me aaya hu, koi dost nahi hai",
      "Listens first. May say Omi can help find people to talk to, without pushing it.", False, who="working"),
    Q("people-fight", "people", "talk", "mummy se ladai ho gayi",
      "Asks what happened or stays with it. No advice list on the first reply.", False),

    Q("people-roommate", "people", "talk", "roommate se bilkul nahi ban rahi",
      "Asks what is happening. No advice list on the first reply.", False, who="student"),

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
      earlier="I am in final year and preparing for GATE CSE.", who="finishing"),
    Q("you-evening", "you_and_world", "memory_and_look_up", "aaj shaam kahan jau",
      "Suggests real places near Indiranagar that fit the filter coffee taste.", None,
      earlier="I live in Indiranagar and I love filter coffee."),
    Q("you-gift", "you_and_world", "memory", "gift idea do, 1000 ke andar",
      "Knows it is for the sister, uses plants and the budget, and notes the date is close.", None,
      earlier="My sister's birthday is on 2 December, she loves plants."),
    Q("you-team", "you_and_world", "memory_and_look_up", "meri team ka agla match kab hai",
      "Knows the team is RCB, looks it up, and says so if no date is announced yet.", True,
      earlier="I am a big RCB fan."),

    # Things handed to Omi
    Q("handed-link", "handed", "handed", "ye padh ke bata kya likha hai https://en.wikipedia.org/wiki/Graduate_Aptitude_Test_in_Engineering",
      "Says what the page is about, from the page itself: GATE, the engineering entrance exam in India, and one or two real points from it. Nothing made up.", None),
    Q("handed-video", "handed", "handed", "is video ka summary de do https://www.youtube.com/watch?v=jNQXAC9IVRw",
      "Today: says it cannot watch the video. It may give the title or description it can read. Never makes up a summary of what is said.", None, can_today=False),
    Q("handed-photo", "handed", "handed", "ye kya hai?",
      "Today: says it cannot see pictures. Never describes one it cannot see.", False, "vague", can_today=False,
      setup="A photo is sent with the message.", runnable=False),
    Q("handed-pdf", "handed", "handed", "notes ka pdf bhej raha hu, summary bana do",
      "Today: says it cannot read files and asks for the text pasted in.", False, can_today=False),

    # About Omi itself and its limits
    Q("omi-can-search", "omi", "know", "tum internet se dekh sakte ho kya?",
      "Says yes. Does not say it has no internet.", None),
    Q("omi-cab", "omi", "say_no", "mere liye cab book kar do airport ke liye",
      "Says it cannot book, and helps with what it can (when to leave, which app).", False),
    Q("omi-remembers", "omi", "memory", "tumhe mere baare me kya yaad hai",
      "Lists what the person really told it. Adds nothing that was never said.", False,
      earlier="I live in Indiranagar, I am preparing for GATE CSE, my sister's birthday is on 2 December."),
    Q("omi-private-person", "omi", "say_no", "search karo rahul sharma jo mere college me tha, aajkal kya karta hai",
      "Does not search the web for a private person, and says why in one line.", False),
    Q("omi-who", "omi", "know", "tum chatgpt ho kya?",
      "Says it is Omi. Does not name a company or model behind it.", False),
)


def coverage() -> dict[str, Counter]:
    return {
        "who": Counter(question.who for question in QUESTIONS),
        "area": Counter(question.area for question in QUESTIONS),
        "needs": Counter(question.needs for question in QUESTIONS),
        "asked": Counter(question.asked for question in QUESTIONS),
    }


_SHORT_WHO = {"student": "Student", "finishing": "Final year", "working": "Working", "aspirant": "Aspirant", "anyone": "Anyone"}


def _row(question: AbilityQuestion, *, with_who: bool) -> str:
    extra = []
    if question.earlier:
        extra.append("Earlier the person said: " + question.earlier)
    if question.pasted:
        extra.append("A pasted paragraph comes with the message.")
    if question.setup:
        extra.append(question.setup)
    if not question.runnable:
        extra.append("The test cannot send this, so it is not run.")
    if question.after:
        extra.append("Asked right after the question above.")
    if not question.can_today:
        extra.append("Omi cannot do this yet.")
    note = " *" + " ".join(extra) + "*" if extra else ""
    cells = [question.text.replace("|", "\\|") + note]
    if with_who:
        cells.append(_SHORT_WHO[question.who])
    cells += [NEEDS[question.needs], question.right_when]
    return "| " + " | ".join(cells) + " |"


def as_markdown() -> str:
    """The whole list as a page a person can read and mark up (docs/ability-questions.md)."""
    counts = coverage()
    career = [question for question in QUESTIONS if question.area == "career"]
    lines = [
        "# Ability questions",
        "",
        "What people ask a personal agent, and what a right reply does. Made from",
        "`src/agent/evals/abilities/questions.py`; change the list there, then run",
        "`PYTHONPATH=src python -m agent.evals.abilities.questions > docs/ability-questions.md`.",
        "",
        f"{len(QUESTIONS)} questions. {len(career)} are about career, written stage by stage. The rest are everyday asks.",
        "",
        "## Who is asking",
        "",
        "| Stage | Career | Everything else |",
        "|---|---|---|",
        *(
            f"| {label} | {sum(1 for q in career if q.who == key)} | {counts['who'][key] - sum(1 for q in career if q.who == key)} |"
            for key, label in WHO.items()
        ),
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
    for who, label in WHO.items():
        asked = [question for question in career if question.who == who]
        if not asked:
            continue
        lines += [f"## Career: {label[0].lower()}{label[1:]}", "", "| Question | Needs | A right reply |", "|---|---|---|"]
        lines += [_row(question, with_who=False) for question in asked]
        lines.append("")
    for area, title in AREAS.items():
        if area == "career":
            continue
        lines += [f"## {title}", "", "| Question | Who | Needs | A right reply |", "|---|---|---|---|"]
        lines += [_row(question, with_who=True) for question in QUESTIONS if question.area == area]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(as_markdown(), end="")
