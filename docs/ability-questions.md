# Ability questions

What people ask a personal agent, and what a right reply does. Made from
`src/agent/evals/abilities/questions.py`; change the list there, then run
`PYTHONPATH=src python -m agent.evals.abilities.questions > docs/ability-questions.md`.

125 questions. 41 are about career, written stage by stage. The rest are everyday asks.

## Who is asking

| Stage | Career | Everything else |
|---|---|---|
| In college, first to third year (about 18 to 21) | 11 | 6 |
| Final year or just out, after a first job or more study (about 21 to 23) | 15 | 6 |
| In the first few years of a job (about 22 to 27) | 13 | 6 |
| Preparing full time for a government or entrance exam | 2 | 4 |
| Anyone | 0 | 62 |

## What Omi must do to be right

| What it needs | Questions |
|---|---|
| Answer from what it knows or can work out | 25 |
| Look up a fact that changes | 31 |
| Look up, then reason about dates (still open? how long left?) | 13 |
| Look up more than one thing and put it together | 3 |
| Find real places | 3 |
| Use what the person told it before | 5 |
| Use what it knows about the person and look something up | 4 |
| Do something at a later time | 2 |
| Read a thing it is given | 4 |
| Help decide, with a clear view and the reason | 8 |
| Ask one short question back, because the ask is unclear | 2 |
| Say honestly it cannot or should not, and offer what it can | 3 |
| Write something ready to send | 10 |
| Be a good friend to talk to | 12 |

Must search: 43. Must not search: 52. Either: 30. Omi cannot do it yet: 5.

## Career: in college, first to third year (about 18 to 21)

| Question | Needs | A right reply |
|---|---|---|
| 2nd year me hu, internship kaise milegi | Answer from what it knows or can work out | Three or four steps a second-year student can start this week. Not a list of ten general tips. |
| summer 2027 internship ke liye abhi kaunsi companies ke form open hain | Look up, then reason about dates (still open? how long left?) | Real programmes that are open now, each with its last date. Says which are already closed. |
| dsa karu ya development, placement ke liye kya zyada kaam aata hai | Help decide, with a clear view and the reason | Gives a clear view and why. May ask the year or branch once. Does not end on 'both are important'. |
| cgpa 6.8 hai, placement me dikkat hogi? | Answer from what it knows or can work out | Honest: some companies have a cutoff. Then what still works at 6.8. No false comfort. |
| mechanical se hu, software job mil sakti hai? | Answer from what it knows or can work out | Says yes and how people do it, in a few lines. |
| ek 40k ka data science course hai, lena chahiye kya | Help decide, with a clear view and the reason | A clear view. Asks what it is for or names free ways to learn the same. Does not sell the course. |
| resume me kya likhu, koi experience nahi hai | Write something ready to send | Says what a student with no job can put, and offers to draft it. Invents no experience. |
| gsoc 2027 kab start hoga | Look up, then reason about dates (still open? how long left?) | The real timeline, or says it is not announced yet. Not last year's dates as this year's. |
| ek professor ko research internship ke liye mail likh do | Write something ready to send | A short mail ready to send, with blanks only where it needs the person's own details. |
| sabko internship mil gayi, mujhe nahi mili | Be a good friend to talk to | Stays with the feeling first. At most one small next step. No advice list. |
| is semester me career ke liye kya karu *Earlier the person said: I am in second year ECE, I like UI design, I have no internship yet.* | Use what the person told it before | Uses the branch, the interest in design and the missing internship. An answer only this person would get. |

## Career: final year or just out, after a first job or more study (about 21 to 23)

| Question | Needs | A right reply |
|---|---|---|
| any off campus drives going on for 2026 batch? | Look up a fact that changes | Names real current drives with dates or sources, or says it could not confirm any. Makes none up. |
| tcs fresher salary kitni hoti hai 2026 mein | Look up a fact that changes | Gives a range with where it is from, and says it differs by role. |
| tcs nqt ka next exam kab hai | Look up, then reason about dates (still open? how long left?) | The next real date and the last date to register, or says it is not announced. |
| 2 offer hain: 6 lpa service company bangalore, 4.5 lpa startup pune jahan kaam accha hai. kaunsa lu | Help decide, with a clear view and the reason | Leans one way, says why, and says what would change the answer. At most one question back. |
| mtech karu ya job | Help decide, with a clear view and the reason | Asks the one thing it needs, or gives a view with the reason. Not only 'it depends'. |
| ms ke liye gre zaruri hai kya fall 2027 ke liye | Look up a fact that changes | Says what universities ask now, that it differs by university, from a search. |
| placement nahi hua, sab dost place ho gaye | Be a good friend to talk to | Stays with it first. Then one real next step. No pep talk. |
| 50 jagah apply kiya, kahin se reply nahi aaya | Be a good friend to talk to | Says this is common, then finds what to fix: asks how they apply, or gives two changes. |
| fresher role me bhi 2 saal experience maang rahe hain, kya karu | Answer from what it knows or can work out | Practical ways around it: apply anyway, what counts as experience. Short. |
| kal amazon sde interview hai, kya puchte hain | Answer from what it knows or can work out | Short, useful prep for that interview. Does not turn into a lecture. |
| interview me expected salary puche toh kya bolu, fresher hu | Answer from what it knows or can work out | A line the person can say, and how to pick the number. |
| offer letter me 2 saal ka bond hai 2 lakh ka, sign karu? | Help decide, with a clear view and the reason | Explains what the bond means, what to check before signing, and gives a view. Does not claim to be a lawyer. |
| hr ko follow up mail likh do, interview ko 1 hafta ho gaya | Write something ready to send | A short, polite mail ready to send. |
| linkedin pe referral maangne ka message likh do | Write something ready to send | A short message that does not beg, with a blank for the role. |
| mere liye koi opening dekh ke batao *Earlier the person said: I am in final year CSE, 7.4 CGPA, I want backend roles, I am in Bhopal.* | Use what it knows about the person and look something up | Looks for backend fresher roles that fit, without asking again what the person wants. |

## Career: in the first few years of a job (about 22 to 27)

| Question | Needs | A right reply |
|---|---|---|
| notice period buyout kya hota hai | Answer from what it knows or can work out | Explains it simply and right. |
| is it true infosys is laying off? | Look up a fact that changes | Says what recent news reports, with dates, and says so when it is not confirmed. |
| switch pe 30% hike normal hai kya abhi | Look up a fact that changes | What recent reports say for this year, with the source. Not a number from memory. |
| job chhodne ke baad pf kaise nikalte hain | Look up a fact that changes | The steps under the current rules, short. |
| 1 saal ho gaya company me, switch karu ya ruku | Help decide, with a clear view and the reason | Asks the one thing that matters, or gives a view with the reason. |
| 2 saal job ke baad mba karna worth hai kya | Help decide, with a clear view and the reason | A clear view with the reason, and what it depends on in one line. |
| job ke saath freelancing kar sakta hu kya | Answer from what it knows or can work out | Says it depends on the contract and what to check. Does not just say yes. |
| appraisal me hike nahi mila, manager se kaise baat karu | Be a good friend to talk to | How to raise it, and a line or two the person can say. |
| manager weekend pe bhi kaam karwata hai, mana kaise karu | Be a good friend to talk to | A way to say no that keeps the job safe, with words to use. |
| roz office jaane ka mann nahi karta | Be a good friend to talk to | Asks what is going on. No productivity tips on the first reply. |
| resignation mail likh do, 2 month notice hai | Write something ready to send | A short mail ready to send. |
| offer aaya hai 9 lpa, 11 kaise maangu, mail likh do | Write something ready to send | A mail that asks for 11 with a reason, ready to send. |
| agle 3 mahine me kya seekhu *Earlier the person said: I have been a manual tester at a service company for 1.5 years and I want to move to development.* | Use what the person told it before | Uses the testing job and the wish to move to development. A plan only this person would get. |

## Career: preparing full time for a government or entrance exam

| Question | Needs | A right reply |
|---|---|---|
| 3 attempt ho gaye, clear nahi hua, ab kya karu | Be a good friend to talk to | Takes it seriously, asks or reflects first. No quick fix. |
| upsc ke saath koi backup rakhna chahiye kya | Help decide, with a clear view and the reason | A clear view with the reason. |

## Exams and admissions

| Question | Who | Needs | A right reply |
|---|---|---|---|
| gate ka form kab open hoga? | Final year | Look up, then reason about dates (still open? how long left?) | Says the GATE 2027 form opened on 2 September 2026 and has closed (5 October, 12 October with late fee). Never gives it as coming up. |
| cat admit card aa gaya kya | Final year | Look up a fact that changes | Says whether the CAT 2026 admit card is out, with the date, from a search. |
| aur exam kab hai? *Asked right after the question above.* | Final year | Look up, then reason about dates (still open? how long left?) | Understands it is still about CAT, gives the exam date and how many days are left. |
| can i give gate in 3rd year btech? | Student | Look up a fact that changes | Says yes, with the official rule (third year or above of a degree). |
| form kab aayega | Anyone | Ask one short question back, because the ask is unclear | No exam is named and Omi knows none: asks which exam, in one short line. Does not guess. |
| gate aur cat dono de sakta hu kya same year, dates clash toh nahi? | Final year | Look up more than one thing and put it together | Gives both exam dates and says clearly whether they clash. |
| kitne din bache hain mere exam mein? *Earlier the person said: My semester exams start on 7 December.* | Student | Use what the person told it before | Uses the date the person gave and counts the days right for today. |
| ssc cgl tier 1 kab hai | Aspirant | Look up, then reason about dates (still open? how long left?) | The real date for the current cycle and how far away it is. |
| upsc prelims 2027 kab hai | Aspirant | Look up, then reason about dates (still open? how long left?) | The date from the official calendar, or says it is not out yet. |
| bank po ke liye age limit kya hai | Aspirant | Look up a fact that changes | The age limit and the usual relaxations, with the source. |
| aaj ke current affairs bata do exam ke liye | Aspirant | Look up a fact that changes | Real items from today or yesterday, short, the kind an exam asks. |

## Forms, documents and schemes

| Question | Who | Needs | A right reply |
|---|---|---|---|
| passport banwane mein kitna time lagta hai aur fees? | Anyone | Look up a fact that changes | Gives the current fee and the usual time, from an official or recent source. |
| aadhaar me address online change ho sakta hai? | Anyone | Look up a fact that changes | Says yes and how, in two or three steps. |
| koi scholarship hai kya obc btech students ke liye, last date? | Student | Look up, then reason about dates (still open? how long left?) | Names real scholarships with their last dates, and says which are already closed. |
| itr bharne ki last date kya hai | Working | Look up, then reason about dates (still open? how long left?) | The date for this year, and whether it has passed. |
| pan aadhaar link last date kya hai | Anyone | Look up, then reason about dates (still open? how long left?) | Gives the current rule or deadline with its date, not an old one. |

## Money and prices

| Question | Who | Needs | A right reply |
|---|---|---|---|
| aaj gold rate kya hai | Anyone | Look up a fact that changes | Gives today's rate with the city or source and the date. |
| 50k ka phone 12 month no cost emi pe, monthly kitna | Anyone | Answer from what it knows or can work out | About 4,167 a month. Works it out, does not search. |
| upi ki daily limit kitni hai | Anyone | Look up a fact that changes | Gives the general limit and says it differs by bank and kind of payment. |
| 12 lpa pe kitna tax lagega new regime | Working | Look up more than one thing and put it together | Uses this year's slabs, shows the rough working, names the year. |
| petrol price in bangalore today | Anyone | Look up a fact that changes | Gives today's price with the date. |
| ghar se mahine ka 8000 milta hai, kaise manage karu | Student | Answer from what it knows or can work out | A simple split for a student budget. Short. |
| pehli salary aayi hai, kahan lagau paise | Working | Answer from what it knows or can work out | General first steps like an emergency fund. Pushes no product and says it is not personal investment advice. |
| hsr layout me 1bhk ka rent kitna chal raha hai | Working | Look up a fact that changes | A current range with where it is from. |

## Travel and getting around

| Question | Who | Needs | A right reply |
|---|---|---|---|
| tatkal booking kitne baje khulti hai | Anyone | Look up a fact that changes | Gives the right opening times for AC and non-AC, one day before the journey. |
| bhopal se delhi sabse fast train kaunsi hai | Anyone | Look up a fact that changes | Names a real train and its travel time. |
| last metro from majestic to whitefield kitne baje | Anyone | Look up a fact that changes | Gives a time with its source, or says it could not confirm. Does not guess a time. |
| cheapest flight blr to del next friday | Anyone | Look up a fact that changes | Works out which date next Friday is, gives a rough fare range or where to check, invents no exact fare, and does not claim to book. |
| mysore kitna door hai bangalore se, bike se kitna time | Anyone | Answer from what it knows or can work out | About 145 km and about 3 hours. |

## Food, places and outings

| Question | Who | Needs | A right reply |
|---|---|---|---|
| indiranagar me koi accha cafe bata kaam karne ke liye | Anyone | Find real places | Two or three real cafes in Indiranagar, found with the places tool, with why each fits working. |
| is truffles koramangala open right now? | Anyone | Find real places | Gives its hours and whether it is open at this time, or says it cannot confirm live. |
| is weekend bangalore me kya ho raha hai | Anyone | Look up a fact that changes | Real events for the coming weekend, with dates. |
| which movies are running in theatres rn | Anyone | Look up a fact that changes | Names films in theatres now, from a search. |
| koi accha biryani place near me | Anyone | Ask one short question back, because the ask is unclear | Omi does not know where the person is: asks the area in one short line. |

## Sports and entertainment

| Question | Who | Needs | A right reply |
|---|---|---|---|
| score kya hai | Anyone | Look up a fact that changes | Finds the India match on now or the latest one, says which match and when, gives the score. |
| india ka next match kab hai | Anyone | Look up, then reason about dates (still open? how long left?) | Gives the next match, date and opponent, counted from today. |
| kahan dekh sakte hain? *Asked right after the question above.* | Anyone | Look up a fact that changes | Understands it is about that match and says where it is shown. |
| koi acchi nayi web series aayi hai kya is hafte | Anyone | Look up a fact that changes | Names real releases from the last week or two. |
| ipl 2026 kisne jeeta | Anyone | Look up a fact that changes | Names the right winner. This happened after many models stopped learning, so it must look it up. |
| sachin ke kitne international centuries hain | Anyone | Answer from what it knows or can work out | 100. No search needed. |

## News and what is new

| Question | Who | Needs | A right reply |
|---|---|---|---|
| aaj ki badi khabar kya hai | Anyone | Look up a fact that changes | Two or three real items from today or yesterday, each with source and date. |
| ai me kya naya chal raha hai | Anyone | Look up a fact that changes | Real items from the last week, not what the model remembers from training. |
| bangalore me aaj bandh hai kya? | Anyone | Look up a fact that changes | Says what it found with the date. If nothing is found, says so and does not guess. |
| suna hai 500 ka note band ho raha hai, sach hai? | Anyone | Look up a fact that changes | Checks, and says what official sources say. Does not confirm a rumour. |

## Health and body

| Question | Who | Needs | A right reply |
|---|---|---|---|
| 2 din se bukhar hai 101, kya karu | Anyone | Be a good friend to talk to | Sensible care steps and when to see a doctor. No diagnosis. |
| dolo 650 din me kitni baar le sakte hain | Anyone | Answer from what it knows or can work out | The usual label guidance with the gap between doses, and says to check with a doctor or chemist. |
| chest me dard ho raha hai aur left arm sunn hai | Anyone | Say honestly it cannot or should not, and offer what it can | Tells them to get emergency help now, short and clear. No long advice, no search first. |
| protein kitna lena chahiye 70kg gym beginner | Anyone | Answer from what it knows or can work out | A sensible range in grams per day for that weight. |

## Study help and how-to

| Question | Who | Needs | A right reply |
|---|---|---|---|
| explain recursion like im 5 | Anyone | Answer from what it knows or can work out | A simple, right explanation with one small example. |
| integrate x e^x | Anyone | Answer from what it knows or can work out | x e^x minus e^x plus C. |
| python me list reverse kaise karte hain | Anyone | Answer from what it knows or can work out | Shows a right way in a line or two. |
| gate cse 6 months me kaise prepare karu | Final year | Answer from what it knows or can work out | A short plan a person can follow. At most one question back. |

## Writing for me

| Question | Who | Needs | A right reply |
|---|---|---|---|
| boss ko message likh do kal chutti chahiye, fever hai | Working | Write something ready to send | A short message ready to send, in a normal office tone. |
| she said 'k fine'. kya reply karu | Anyone | Write something ready to send | One or two replies in the person's own way of talking, not a lecture on feelings. |
| is this correct: 'I didn't went there' | Anyone | Answer from what it knows or can work out | Says it is wrong, gives the right sentence, one line on why. |
| linkedin bio likh do, 3rd year cse, ml me interest | Student | Write something ready to send | A bio ready to paste, using only what was said. Invents no jobs or awards. |
| isko 3 line me bata do *A pasted paragraph comes with the message.* | Anyone | Write something ready to send | Three lines that keep the main points of the pasted text. |

## People and feelings

| Question | Who | Needs | A right reply |
|---|---|---|---|
| my friend isnt able to move on from a 5 year relationship, she cries all day, what can i do for her | Anyone | Be a good friend to talk to | Warm and practical, a few things the person can do, and a counsellor if it stays this bad. Shows only the reply, never notes to itself. |
| naye sheher me aaya hu, koi dost nahi hai | Working | Be a good friend to talk to | Listens first. May say Omi can help find people to talk to, without pushing it. |
| mummy se ladai ho gayi | Anyone | Be a good friend to talk to | Asks what happened or stays with it. No advice list on the first reply. |
| roommate se bilkul nahi ban rahi | Student | Be a good friend to talk to | Asks what is happening. No advice list on the first reply. |

## Shopping and tech

| Question | Who | Needs | A right reply |
|---|---|---|---|
| 20k ke under best phone kaunsa hai abhi | Anyone | Look up more than one thing and put it together | Two or three phones on sale now with why, from a search. No models from two years ago. |
| macbook air ya windows laptop coding ke liye, 70k budget | Anyone | Answer from what it knows or can work out | A clear pick with the reason. Checks prices if it names them. |
| ps5 ka price kya chal raha hai india me | Anyone | Look up a fact that changes | The current price with the date or source. |
| flipkart ki next sale kab hai | Anyone | Look up, then reason about dates (still open? how long left?) | The next sale and its dates, or says no date is announced. Not a sale that is over. |

## Time, dates, reminders and plans

| Question | Who | Needs | A right reply |
|---|---|---|---|
| 14 december ko kaunsa din hai | Anyone | Answer from what it knows or can work out | The right weekday for the coming 14 December. |
| abhi time kya hua hai | Anyone | Answer from what it knows or can work out | The right time where the person is. |
| next long weekend kab hai | Anyone | Look up, then reason about dates (still open? how long left?) | The next real long weekend counted from today. |
| remind me at 6 to call mom *Omi cannot do this yet.* | Anyone | Do something at a later time | Says honestly it cannot set a reminder for a time yet. Never says 'done, I will remind you'. |
| kal interview hai, kal shaam puch lena kaisa gaya *Omi cannot do this yet.* | Anyone | Do something at a later time | Promises only what it will really do. If it cannot write first tomorrow, it says so. |
| sunday ko free hu, ek plan bana do bangalore me | Anyone | Find real places | A short plan with real places and rough times. |

## What Omi knows about you, plus a look-up

| Question | Who | Needs | A right reply |
|---|---|---|---|
| mujhe abhi kaunsi dates yaad rakhni chahiye? *Earlier the person said: I am in final year and preparing for GATE CSE.* | Final year | Use what it knows about the person and look something up | Knows it is about GATE without being told again, and gives the real coming dates (admit card, exam). |
| aaj shaam kahan jau *Earlier the person said: I live in Indiranagar and I love filter coffee.* | Anyone | Use what it knows about the person and look something up | Suggests real places near Indiranagar that fit the filter coffee taste. |
| gift idea do, 1000 ke andar *Earlier the person said: My sister's birthday is on 2 December, she loves plants.* | Anyone | Use what the person told it before | Knows it is for the sister, uses plants and the budget, and notes the date is close. |
| meri team ka agla match kab hai *Earlier the person said: I am a big RCB fan.* | Anyone | Use what it knows about the person and look something up | Knows the team is RCB, looks it up, and says so if no date is announced yet. |

## Things handed to Omi: a link, a photo, a file

| Question | Who | Needs | A right reply |
|---|---|---|---|
| ye padh ke bata kya likha hai https://en.wikipedia.org/wiki/Graduate_Aptitude_Test_in_Engineering | Anyone | Read a thing it is given | Says what the page is about, from the page itself: GATE, the engineering entrance exam in India, and one or two real points from it. Nothing made up. |
| is video ka summary de do https://www.youtube.com/watch?v=jNQXAC9IVRw *Omi cannot do this yet.* | Anyone | Read a thing it is given | Today: says it cannot watch the video. It may give the title or description it can read. Never makes up a summary of what is said. |
| ye kya hai? *A photo is sent with the message. The test cannot send this, so it is not run. Omi cannot do this yet.* | Anyone | Read a thing it is given | Today: says it cannot see pictures. Never describes one it cannot see. |
| notes ka pdf bhej raha hu, summary bana do *Omi cannot do this yet.* | Anyone | Read a thing it is given | Today: says it cannot read files and asks for the text pasted in. |

## About Omi itself and its limits

| Question | Who | Needs | A right reply |
|---|---|---|---|
| tum internet se dekh sakte ho kya? | Anyone | Answer from what it knows or can work out | Says yes. Does not say it has no internet. |
| mere liye cab book kar do airport ke liye | Anyone | Say honestly it cannot or should not, and offer what it can | Says it cannot book, and helps with what it can (when to leave, which app). |
| tumhe mere baare me kya yaad hai *Earlier the person said: I live in Indiranagar, I am preparing for GATE CSE, my sister's birthday is on 2 December.* | Anyone | Use what the person told it before | Lists what the person really told it. Adds nothing that was never said. |
| search karo rahul sharma jo mere college me tha, aajkal kya karta hai | Anyone | Say honestly it cannot or should not, and offer what it can | Does not search the web for a private person, and says why in one line. |
| tum chatgpt ho kya? | Anyone | Answer from what it knows or can work out | Says it is Omi. Does not name a company or model behind it. |
