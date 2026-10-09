// 👍/👎 on Omi's replies, from the message ⋯ menu. One rating per message.

export type ReplyRating = "good" | "bad";

// What was off with a bad reply. Keys match the backend's feedback reasons.
export const BAD_REPLY_REASONS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "too_much", label: "Too long" },
  { key: "bad_tone", label: "Wrong tone" },
  { key: "wrong_memory", label: "Got me wrong" },
  { key: "not_helpful", label: "Not helpful" },
];

// Saved ratings come newest first; "off" and "harmful" from older builds count as bad.
export function ratingsByMessage(feedback: Array<{ message_index: number; rating: string }>): Map<number, ReplyRating> {
  const ratings = new Map<number, ReplyRating>();
  for (const item of feedback) {
    if (ratings.has(item.message_index)) continue;
    ratings.set(item.message_index, item.rating === "good" ? "good" : "bad");
  }
  return ratings;
}

export function withRating(ratings: ReadonlyMap<number, ReplyRating>, index: number, rating: ReplyRating | null): Map<number, ReplyRating> {
  const next = new Map(ratings);
  if (rating) next.set(index, rating);
  else next.delete(index);
  return next;
}
