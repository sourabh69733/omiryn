export type OnboardingStep = {
  id: string;
  progress: string;
  question: string;
  hint?: string;
  placeholder?: string;
  type: "text" | "date" | "choice" | "photo";
  optional?: boolean;
  choices?: Array<{
    label: string;
    value: string;
  }>;
};

export const onboardingSteps: OnboardingStep[] = [
  {
    id: "name",
    progress: "1 of 7",
    question: "First tiny question. What should I call you?",
    placeholder: "Type your name",
    type: "text"
  },
  {
    id: "dob",
    progress: "2 of 7",
    question: "What’s your date of birth?",
    hint: "Use YYYY-MM-DD.",
    type: "date"
  },
  {
    id: "interested",
    progress: "3 of 7",
    question: "Who are you interested in meeting?",
    type: "choice",
    choices: [
      { label: "Women", value: "women" },
      { label: "Men", value: "men" },
      { label: "Everyone", value: "everyone" }
    ]
  },
  {
    id: "gender",
    progress: "4 of 7",
    question: "How should we describe your gender?",
    type: "choice",
    choices: [
      { label: "Man", value: "man" },
      { label: "Woman", value: "woman" },
      { label: "Non-binary", value: "non_binary" },
      { label: "Prefer not to say", value: "prefer_not_to_say" }
    ]
  },
  {
    id: "state",
    progress: "5 of 7",
    question: "Which state are you in?",
    placeholder: "Karnataka",
    type: "text"
  },
  {
    id: "city",
    progress: "6 of 7",
    question: "And which city?",
    placeholder: "Bengaluru",
    type: "text"
  },
  {
    id: "phone",
    progress: "7 of 7",
    question: "Want to add a phone number?",
    hint: "Optional. You can skip this.",
    placeholder: "+91...",
    optional: true,
    type: "text"
  },
  {
    id: "photos",
    progress: "8 of 8",
    question: "Want to add a profile photo now?",
    hint: "Totally optional, but it helps people recognize you.",
    optional: true,
    type: "photo"
  }
];
