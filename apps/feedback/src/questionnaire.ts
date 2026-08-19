export type Question = {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  type: "single" | "multiple" | "text";
  maxChoices?: number;
  options?: string[];
  exclusiveOptions?: string[];
};

export const questions: Question[] = [
  {
    id: "compatibility_challenges",
    eyebrow: "The hard part",
    title: "What makes finding a compatible person difficult?",
    description: "Select as many as apply — there's no right number.",
    type: "multiple",
    options: [
      "Meeting the right people",
      "Understanding real intentions",
      "Knowing if values and personalities match",
      "Starting a meaningful conversation",
      "Trust and personal safety",
      "Too many low-quality or repetitive matches",
      "Social pressure or awkwardness",
      "Limited time or opportunities",
      "I don't think it is particularly difficult",
    ],
    exclusiveOptions: ["I don't think it is particularly difficult"],
  },
  {
    id: "compatibility_signals",
    eyebrow: "What matters",
    title: "What matters most when deciding whether someone could be compatible?",
    description: "Pick the factors that carry the most weight for you.",
    type: "multiple",
    options: [
      "Shared values",
      "Similar relationship intentions",
      "Personality",
      "Communication style",
      "Lifestyle",
      "Interests",
      "Family or cultural background",
      "Physical attraction",
    ],
  },
  {
    id: "ai_disclosure_comfort",
    eyebrow: "Getting to know you",
    title: "How comfortable would you be talking openly with an AI companion about yourself — your values, past relationships, what you're really looking for?",
    description: "Imagine it's a private, ongoing conversation the AI uses to understand you better over time, not a form to fill out.",
    type: "single",
    options: [
      "Very comfortable",
      "Somewhat comfortable",
      "Depends on what's asked",
      "Not very comfortable",
      "Not comfortable at all",
    ],
  },
  {
    id: "depth_vs_speed",
    eyebrow: "The tradeoff",
    title: "Would you rather get matches faster or wait longer for the AI to understand you more deeply first?",
    description: "There's no wrong answer — we just want to know what you'd actually prefer.",
    type: "single",
    options: [
      "Match me quickly, even if less accurate",
      "Take your time, I want it to really understand me",
      "Somewhere in between",
      "Not sure",
    ],
  },
  {
    id: "intro_time_willingness",
    eyebrow: "The time trade-off",
    title: "How much time would you spend before receiving your first introduction?",
    description: "Choose the maximum that would still feel reasonable.",
    type: "single",
    options: [
      "Under 10 minutes",
      "10-15 minutes",
      "20-30 minutes",
      "More than 60 minutes",
      "I would not want to do this",
    ],
  },
  {
    id: "concept_concerns",
    eyebrow: "A healthy doubt",
    title: "What would concern you most about an idea like Omiryn?",
    description: "Select any that resonate - honesty here helps us the most.",
    type: "multiple",
    options: [
      "Privacy and personal data",
      "AI understanding someone incorrectly",
      "Compatibility cannot be predicted",
      "Losing spontaneity or human judgement",
      "Fake profiles and safety",
      "Not enough relevant people",
      "The process taking too much effort",
      "Nothing concerns me yet",
    ],
    exclusiveOptions: ["Nothing concerns me yet"],
  },
  {
    id: "dating_openness",
    eyebrow: "Where you are",
    title: "Are you currently open to meeting someone for dating or a relationship?",
    description: "Choose the answer that feels closest right now.",
    type: "single",
    options: [
      "Actively looking",
      "Open to it",
      "Not looking right now",
      "Prefer not to say",
    ],
  },
  {
    id: "must_get_right",
    eyebrow: "Be candid",
    title: "What is the one thing Omiryn must get right?",
    description: "Optional: share a feature, concern, flaw, or something we may have completely missed.",
    type: "text",
  },
];

export const conceptInsertAfterQuestion = 3;
