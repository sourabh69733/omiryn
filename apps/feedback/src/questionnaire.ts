export type Question = {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  type: "single" | "multiple" | "text";
  maxChoices?: number;
  options?: string[];
};

export const questions: Question[] = [
  {
    id: "meeting_paths",
    eyebrow: "Your world",
    title: "Where do people your age usually meet someone they might connect with?",
    description: "Choose up to two.",
    type: "multiple",
    maxChoices: 2,
    options: [
      "Friends or family",
      "College or work",
      "Shared interests",
      "Events or communities",
      "Social media",
      "Dating apps",
      "Mostly by chance",
      "I'm not sure",
    ],
  },
  {
    id: "compatibility_challenges",
    eyebrow: "The hard part",
    title: "What makes finding a compatible person difficult?",
    description: "Choose up to two.",
    type: "multiple",
    maxChoices: 2,
    options: [
      "Meeting the right people",
      "Understanding real intentions",
      "Knowing if values and personalities match",
      "Starting a meaningful conversation",
      "Trust and personal safety",
      "Social pressure or awkwardness",
      "Limited time or opportunities",
      "I don't think it is particularly difficult",
    ],
  },
  {
    id: "compatibility_signals",
    eyebrow: "What matters",
    title: "What tells you that two people could be compatible?",
    description: "Choose up to three.",
    type: "multiple",
    maxChoices: 3,
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
    id: "concept_usefulness",
    eyebrow: "Your first reaction",
    title: "How useful could this approach be for people your age?",
    description: "There is no right answer. Pick your honest first reaction.",
    type: "single",
    options: [
      "Extremely useful",
      "Quite useful",
      "Somewhat useful",
      "Not very useful",
      "Not useful",
      "I need more information",
    ],
  },
  {
    id: "concept_concerns",
    eyebrow: "A healthy doubt",
    title: "What would concern you most about an idea like Omiryn?",
    description: "Choose up to two.",
    type: "multiple",
    maxChoices: 2,
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
