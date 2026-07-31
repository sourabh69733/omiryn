import { apiFetch } from "./api";

type AppEventName =
  | "app_opened"
  | "page_viewed"
  | "chat_opened"
  | "chat_started"
  | "profile_saved"
  | "memory_import_completed"
  | "learned_signal_edited"
  | "learned_signal_deleted"
  | "learned_signal_confirmed"
  | "learned_signal_rejected"
  | "learned_signal_feedback_sent"
  | "learned_signal_privacy_updated"
  | "learned_signal_restored"
  | "data_export_requested"
  | "data_deletion_requested"
  | "feedback_opened"
  | "feedback_submitted"
  | "community_invite_requested"
  | "client_error";

type AppEventMetadata = Record<string, string | number | boolean | null | undefined>;

type QueuedAppEvent = {
  session_id: string;
  event_name: AppEventName;
  page?: string;
  target_type?: string;
  target_id?: string;
  metadata: AppEventMetadata;
  client_created_at: string;
};

const STORAGE_KEY = "omiryn.appEventQueue";
const SESSION_KEY = "omiryn.appSessionId";
const MAX_STORED_EVENTS = 100;
const FLUSH_BATCH_SIZE = 8;
const FLUSH_INTERVAL_MS = 15000;

let queue: QueuedAppEvent[] = [];
let loaded = false;
let initialized = false;
let flushing = false;
let flushTimer: number | null = null;

export function initAppLogger() {
  if (initialized) return;
  initialized = true;
  loadQueue();
  trackAppEvent("app_opened", { page: currentPage() });
  initClientErrorMonitoring();
  scheduleFlush();
  window.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flushAppEvents();
  });
  window.addEventListener("pagehide", () => void flushAppEvents());
}

function initClientErrorMonitoring() {
  window.addEventListener("error", (event) => {
    trackClientError("window_error", errorCode(event.message || "unknown_error"));
  });
  window.addEventListener("unhandledrejection", (event) => {
    trackClientError("unhandled_rejection", errorCode(rejectionReason(event.reason)));
  });
}

function trackClientError(area: string, messageCode: string) {
  trackAppEvent("client_error", { area, message_code: messageCode }, { page: currentPage() });
  void flushAppEvents();
}

export function trackPageView(page: string) {
  trackAppEvent("page_viewed", { page }, { page });
}

export function trackAppEvent(
  eventName: AppEventName,
  metadata: AppEventMetadata = {},
  options: { page?: string; target_type?: string; target_id?: string } = {},
) {
  loadQueue();
  queue.push({
    session_id: sessionId(),
    event_name: eventName,
    page: options.page || currentPage(),
    target_type: options.target_type,
    target_id: options.target_id,
    metadata: safeMetadata(metadata),
    client_created_at: new Date().toISOString(),
  });
  queue = queue.slice(-MAX_STORED_EVENTS);
  persistQueue();
  if (queue.length >= FLUSH_BATCH_SIZE) void flushAppEvents();
  else scheduleFlush();
}

export async function flushAppEvents() {
  loadQueue();
  if (flushing || !queue.length) return;
  flushing = true;
  const events = queue.slice(0, FLUSH_BATCH_SIZE);
  try {
    const response = await apiFetch("/api/me/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
    if (!response.ok) throw new Error("Event flush failed.");
    queue = queue.slice(events.length);
    persistQueue();
  } catch {
    persistQueue();
  } finally {
    flushing = false;
    scheduleFlush();
  }
}

function scheduleFlush() {
  if (flushTimer !== null) return;
  flushTimer = window.setTimeout(() => {
    flushTimer = null;
    void flushAppEvents();
  }, FLUSH_INTERVAL_MS);
}

function loadQueue() {
  if (loaded) return;
  loaded = true;
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    queue = Array.isArray(stored) ? stored.slice(-MAX_STORED_EVENTS) : [];
  } catch {
    queue = [];
  }
}

function persistQueue() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(queue.slice(-MAX_STORED_EVENTS)));
  } catch {
    // Logging should never interrupt the product experience.
  }
}

function sessionId() {
  const existing = window.sessionStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  window.sessionStorage.setItem(SESSION_KEY, id);
  return id;
}

function currentPage() {
  const path = window.location.pathname;
  if (path.startsWith("/app/contact")) return "contact";
  if (path.startsWith("/style")) return "style";
  if (path.startsWith("/matches")) return "matches";
  if (path.startsWith("/profile")) return "profile";
  return "chat";
}

function safeMetadata(metadata: AppEventMetadata) {
  const allowedKeys = new Set([
    "conversation_id",
    "fact_category",
    "source_type",
    "request_type",
    "area",
    "message_code",
    "page",
    "category",
    "channel",
  ]);
  return Object.fromEntries(
    Object.entries(metadata)
      .filter(([key]) => allowedKeys.has(key))
      .map(([key, value]) => [key, typeof value === "string" ? value.slice(0, 160) : value ?? null]),
  );
}

function rejectionReason(reason: unknown) {
  if (reason instanceof Error) return reason.message;
  if (typeof reason === "string") return reason;
  return "unhandled_rejection";
}

function errorCode(message: string) {
  const normalized = message
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, "url")
    .replace(/['"`].*?['"`]/g, "value")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  return normalized || "unknown_error";
}
