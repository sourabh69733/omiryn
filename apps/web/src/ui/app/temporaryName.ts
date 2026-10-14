// A short, playful title for each Temporary Chat, so it never looks like the main Omi chat.
// Each name hints at something that passes: the chat is gone when the user leaves it.
export const TEMPORARY_NAMES = [
  "Thin Air",
  "Smoke Signal",
  "Paper Plane",
  "Ghost Note",
  "Vanishing Ink",
  "Soap Bubble",
  "Shooting Star",
  "Firefly",
  "Morning Fog",
  "Sea Breeze",
  "Sandcastle",
  "Off the Record",
  "Snowflake",
  "Whisper",
  "Half Moon",
  "Quiet Corner"
] as const;

export function temporaryName(random: () => number = Math.random): string {
  return TEMPORARY_NAMES[Math.min(TEMPORARY_NAMES.length - 1, Math.floor(random() * TEMPORARY_NAMES.length))];
}
