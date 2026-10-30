# The problem Omiryn solves first

Written 30 October 2026, rewritten the same day around one niche. One page, so every piece of work can be checked against it. The idea itself is locked in [progress.md](progress.md): an AI you talk to that finds friends you would get along with. This page says who that is for first, what their problem is, and how we know it is working. The niche is an internal choice; it stays out of the mission and the product copy.

## Who

Someone who moved to one city (Pune first) alone for work in the last two months and took a room in a PG or co-living. Usually 22 to 30, first or second job, knows nobody in the city except colleagues.

## Their problem

For the first two months they have no one to get dinner with, go for a walk with, or ask where the good chai is. Weekends are the worst. The options they have all fail them:

- Dating apps have the wrong intent, and saying "just friends" there does not work.
- Meetup and Bumble BFF offer strangers across the whole city; most never show up, and one bad evening ends the attempt.
- Colleagues are colleagues. Talking to them is work.
- ChatGPT can talk, but it cannot introduce them to anyone.

So they wait. Many go home every weekend, and some move out of the city inside a year. The operator loses a resident; the person loses a year.

## What Omiryn does for them

Gets each new resident one person in or near their building to do one small thing with, inside their first month.

How it works for the resident: they message a WhatsApp number from the building's group. Omi talks with them over a few days, not a form. On match day it introduces them to one person nearby with two or three real reasons, suggests a place and a time (the places tool), reminds both the day before, and asks afterwards how it went. If there is no good pair that week, it says so and asks for one more week.

Omi is the host. It is useful the way a friend who knows everyone is useful. It is not sold as a companion, and it does not need to be famous to be used: the reason to message the number is the person, not the AI.

## Why this niche

- The need is acute and dated: the first eight weeks.
- The pool exists before we do: the building and the two next to it. No cold start, no citywide promise.
- Meeting is easy: a chai downstairs, not a cross-city trip.
- Reach is one conversation: the operator, who wants residents to stay longer and already runs a WhatsApp group per building.
- Nothing else does this, and the model is not the moat. The pool and the trust of "one of us in this building" are.

## The one measure

Of new residents who message the number, how many meet one person within 30 days; and of those pairs, how many are still in touch at day 30.

Everything else (messages per day, return rate, memory accuracy, card completeness) is a means to those two numbers.

## The promise, and how it stays honest

- A building is opened only once 20 or more residents have messaged. Nobody outside an opened building can join.
- Matching happens on a fixed day each week, so everyone who joined that week is in the same pool.
- The first pairs are picked by hand from Omi's vibe notes. Matching code is built only when hand-picking stops scaling.
- Thin week: small groups of three or four for a chai instead of pairs.
- The promise is "you will hear from me by Sunday", never "today".

## The loop, and what exists

| Part | What it means | State |
|---|---|---|
| 1. Know enough | Over the week Omi learns how they talk, what they do with free time, what they cannot stand, a few values, plus the plain facts for a meet (area, free evenings, veg or not, budget). Each line with proof. | Mostly built: memories with evidence, vibe card, user card, WhatsApp channel, nudges and follow-ups. Missing: a "ready for match day" mark from how many areas have proof, and the plain-facts asks. |
| 2. Pick | A person reads the vibe notes of the building's pool and picks pairs or small groups; later, code compares two cards and says why. | Not built. Needs an operator view of the pool: who is ready, their notes. |
| 3. Introduce and host | Omi tells both, with the reasons, suggests place and time, reminds the day before. | Not built. The pieces exist: places tool, promise follow-ups, WhatsApp sends. |
| 4. Learn from it | Day 3 and day 30 check-ins; outcomes recorded per pair. | Not built. |

## What this changes

- The next work is parts 1 to 4 for one building, end to end, before any of it is polished. Agent work continues only when it blocks a match day.
- The product's front door is a WhatsApp number in a building's group, not an app store listing. The web app stays for the operator view and for residents who want more.
- The first proof is one building, one match day, five to ten pairs, and the day-30 numbers, however low.

## Not the problem

- Being the best AI companion. Omi has to be good enough that people answer it for a week.
- Being on every channel. WhatsApp is where these residents already are.
- Citywide or nationwide matching. That comes building by building, if at all.

## Open questions

- Which operator first, and what they get: a report per building (how many met), or a cut of a paid tier later.
- Both sides accept before the intro, or Omi opens a three-way chat and lets either leave.
- What a resident sees of the reasons, and whether the other person's vibe notes are ever shown.
- Safety: a report and block path, and what happens when a pair goes badly.
