// While a reply is pending the server hears whether the user is still typing, so Omi can wait for
// the rest. It is only a hint: a signal expires on the server, so a late or lost one costs nothing.
export const TYPING_SIGNAL_EVERY_MS = 1000;

export type TypingSignalState = { lastSentAt: number; signalled: boolean };
export type TypingSignal = "typing" | "stopped" | null;

export function nextTypingSignal(state: TypingSignalState, text: string, replyPending: boolean, now: number): { signal: TypingSignal; state: TypingSignalState } {
  if (!text.trim()) {
    // Cleared the box: nothing more is coming, so Omi need not wait out the signal.
    const signal = state.signalled && replyPending ? "stopped" : null;
    return { signal, state: { lastSentAt: 0, signalled: false } };
  }
  if (!replyPending || now - state.lastSentAt < TYPING_SIGNAL_EVERY_MS) return { signal: null, state };
  return { signal: "typing", state: { lastSentAt: now, signalled: true } };
}

export const NO_TYPING_SIGNAL: TypingSignalState = { lastSentAt: 0, signalled: false };
