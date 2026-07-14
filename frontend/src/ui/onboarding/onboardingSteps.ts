export type OnboardingStep = {
  id: string;
  progress: string;
  question: string;
  hint?: string;
  placeholder?: string;
  type: "text" | "date" | "choice" | "photo";
  choices?: string[];
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
    id: "gender",
    progress: "3 of 7",
    question: "How should we describe your gender?",
    type: "choice",
    choices: ["Man", "Woman", "Non-binary", "Prefer not to say"]
  },
  {
    id: "interested",
    progress: "4 of 7",
    question: "Who are you interested in meeting?",
    type: "choice",
    choices: ["Women", "Men", "Everyone"]
  },
  {
    id: "location",
    progress: "5 of 7",
    question: "Where are you based?",
    hint: "City, State",
    placeholder: "Bengaluru, Karnataka",
    type: "text"
  },
  {
    id: "phone",
    progress: "6 of 7",
    question: "Want to add a phone number?",
    hint: "Optional. You can skip this.",
    placeholder: "+91...",
    type: "text"
  },
  {
    id: "photos",
    progress: "7 of 7",
    question: "Want to add a profile photo now?",
    hint: "Totally optional, but it helps people recognize you.",
    type: "photo"
  }
];
