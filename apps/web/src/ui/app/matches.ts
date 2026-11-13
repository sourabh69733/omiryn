// Matches: the card list behind the Matches page, and the small bits of logic the page needs.
// Shapes follow docs/matching-design.md section 6; the list call is not built yet, so the page
// treats a missing endpoint as "no cards".
import { VIBE_STEPS, vibeStepIndex } from "./vibe";

export type MatchStatus = "asked" | "waiting" | "introduced" | "met" | "still_talking" | "declined" | "no_show" | "expired" | "blocked";

export type MatchLine = { area: string; text: string };

export type MatchPlan = { place: string; when: string; at?: string | null };

export type MatchCard = {
  pair_id: string;
  status: MatchStatus;
  name: string;
  pool_id?: string | null;
  pool_name?: string | null;
  /** One line from the meet facts, e.g. "Lives in your building · free on weekends". */
  meet_line?: string | null;
  reasons: MatchLine[];
  difference: MatchLine | null;
  icebreaker: string | null;
  plan: MatchPlan | null;
  /** True once both shared their number through Omi; the app only shows it. */
  number_shared?: boolean | null;
  asked_at: string;
  answer_by: string | null;
  updated_at?: string | null;
};

export type MatchReadiness = {
  ready: boolean;
  milestone: string;
  areas: { clear: string[]; mentioned: string[]; missing: string[] };
  facts: { known: Record<string, string>; missing: string[] };
  private_allowed: boolean;
  blockers: string[];
};

export type MatchPool = { id: string; name: string; match_weekday: number; joined_at?: string | null };

export type PoolPair = { id: string; pool_id: string; status: string; created_at: string };

export type MatchSplit = { open: MatchCard[]; waiting: MatchCard[]; people: MatchCard[] };

const PEOPLE_STATUSES: MatchStatus[] = ["introduced", "met", "still_talking", "no_show"];

/** The card waiting on the user, the ones waiting on the other person, and the people they met. */
export function splitMatches(cards: MatchCard[]): MatchSplit {
  return {
    open: cards.filter((card) => card.status === "asked"),
    waiting: cards.filter((card) => card.status === "waiting"),
    people: cards.filter((card) => PEOPLE_STATUSES.includes(card.status)),
  };
}

/** Short label next to the page title. */
export function matchesLabel(ready: boolean, split: MatchSplit): string {
  if (split.open.length) return split.open.length === 1 ? "1 for you" : `${split.open.length} for you`;
  if (split.waiting.length) return split.waiting.length === 1 ? "1 waiting" : `${split.waiting.length} waiting`;
  return ready ? "Looking" : "Not yet";
}

/** "You have two days" while there is time; "Closes tomorrow" and "Closes today" at the end. */
export function deadlineLabel(answerBy: string | null | undefined, now: Date = new Date()): string | null {
  if (!answerBy) return null;
  const left = new Date(answerBy).getTime() - now.getTime();
  if (Number.isNaN(left)) return null;
  const hours = left / 3_600_000;
  if (hours <= 24) return "Closes today";
  if (hours < 48) return "Closes tomorrow";
  const days = Math.ceil(hours / 24);
  return `You have ${days === 2 ? "two" : days === 3 ? "three" : String(days)} days`;
}

/** One line under a person's name in the list. */
export function statusLine(card: MatchCard): string {
  switch (card.status) {
    case "introduced":
      return (card.plan ? `Meeting ${card.plan.when} · Omi will remind you` : "You both said hi") + sharedNote(card);
    case "met":
      return "Met · how did it go?" + sharedNote(card);
    case "still_talking":
      return "Met · still talking" + sharedNote(card);
    case "no_show":
      return "Didn't happen";
    case "waiting":
      return `You said hi · waiting for ${card.name}`;
    default:
      return "";
  }
}

const sharedNote = (card: MatchCard) => (card.number_shared ? " · numbers shared" : "");

/** Why someone reports a match. The reason goes to the team, never to the other person. */
export const REPORT_REASONS = [
  { id: "uncomfortable", label: "Made me uncomfortable" },
  { id: "not_who_they_said", label: "Not who they said they were" },
  { id: "spam", label: "Selling or spam" },
  { id: "other", label: "Something else" },
] as const;

const WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"];

/** Python weekday numbering: Monday is 0. */
export function matchDayLabel(weekday: number): string {
  return WEEKDAYS[((weekday % 7) + 7) % 7] ?? "weekly";
}

/** One line for a group: what Omi is doing there for this user. */
export function poolLine(pool: MatchPool, pairs: PoolPair[], cards: MatchCard[]): string {
  const open = cards.filter((card) => card.pool_id === pool.id && card.status === "asked").length;
  const waiting = cards.filter((card) => card.pool_id === pool.id && card.status === "waiting").length;
  if (open) return open === 1 ? "1 intro" : `${open} intros`;
  if (waiting) return "Waiting";
  const proposed = pairs.filter((pair) => pair.pool_id === pool.id && pair.status === "proposed").length;
  return proposed ? "Waiting" : "Looking";
}

const FACT_WORDS: Record<string, { label: string; hint: string }> = {
  area: { label: "Where you live", hint: "The area, so a first meet is close." },
  free_time: { label: "When you're free", hint: "Evenings, weekends, whatever is true." },
  food: { label: "What you eat", hint: "Veg, non-veg, anything. So the place fits." },
  spending: { label: "How you like to spend", hint: "Chai money or dinner money. No judgement." },
  budget: { label: "How you like to spend", hint: "Chai money or dinner money. No judgement." },
};

/* Good to have for the plan, never a blocker; the readiness call says so too. */
const OPTIONAL_FACTS = new Set(["food", "budget"]);

export type NeedItem = { id: string; label: string; hint: string; done: boolean };

/** What Omi still needs before this user can be matched, in plain words, with what is already clear. */
export function needsList(readiness: MatchReadiness): NeedItem[] {
  const items: NeedItem[] = [];
  const step = vibeStepIndex(readiness.milestone);
  const readyStep = vibeStepIndex("ready_to_match");
  if (step < readyStep) {
    const at = VIBE_STEPS[Math.max(step, 0)]?.label ?? "the start";
    items.push({ id: "vibe", label: "A fuller sense of you", hint: `Your vibe is at "${at}". Matches need "Ready to match".`, done: false });
  } else {
    items.push({ id: "vibe", label: "Your humor, your days, what you love", hint: "Clear from your chats.", done: true });
  }
  for (const id of readiness.facts.missing) {
    if (OPTIONAL_FACTS.has(id)) continue;
    const words = FACT_WORDS[id] ?? { label: id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), hint: "Omi will ask when it fits." };
    items.push({ id, label: words.label, hint: words.hint, done: false });
  }
  for (const id of Object.keys(readiness.facts.known)) {
    const words = FACT_WORDS[id] ?? { label: id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), hint: "" };
    items.push({ id, label: words.label, hint: "Clear from your chats.", done: true });
  }
  return items.sort((a, b) => Number(a.done) - Number(b.done));
}

/** Initial for the avatar when there is no photo. */
export function initialOf(name: string): string {
  return (name.trim()[0] ?? "?").toUpperCase();
}
