export function toggleAnswer(input: {
  type: "single" | "multiple";
  selected: string[];
  option: string;
  maxChoices?: number;
}): string[];
