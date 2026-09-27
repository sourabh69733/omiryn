import type { Message } from "./types";

// Matches the server: a reply still "sending" after two minutes was lost and can be retried.
export const STALE_SENDING_MS = 120000;

// A user message whose reply failed; it stays in the chat and shows Retry.
export function isFailedMessage(message: Message, now = Date.now()) {
  if (message.role !== "user") return false;
  if (message.delivery_status === "failed") return true;
  const sentAt = message.created_at ? Date.parse(message.created_at) : NaN;
  return message.delivery_status === "sending" && Number.isFinite(sentAt) && now - sentAt > STALE_SENDING_MS;
}
