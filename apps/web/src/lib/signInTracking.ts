// Sign-in steps: shown, started, then on return from Google succeeded, failed or abandoned.
// Before sign-in there is no account, so those steps go to the public event endpoint under the
// same browser session id the signed-in events use, which lets the admin join the two.
import { apiFetch } from "./api";
import { APP_RELEASE, sessionId, trackAppEvent } from "./appLogger";
import { signInErrorFromUrl } from "./experienceMetrics";

const STARTED_KEY = "omiryn.signInStartedAt";

type PublicSignInEvent = "sign_in_screen_viewed" | "sign_in_started" | "sign_in_failed" | "sign_in_abandoned";

function trackPublicEvent(eventName: PublicSignInEvent, metadata: Record<string, string | number> = {}) {
  void apiFetch("/api/public/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId(),
      event_name: eventName,
      path: window.location.pathname,
      referrer: document.referrer || null,
      metadata: { ...metadata, source: "app", release: APP_RELEASE },
    }),
  }).catch(() => undefined);
}

export function trackSignInScreen() {
  trackPublicEvent("sign_in_screen_viewed");
}

export function trackSignInStarted() {
  try {
    window.sessionStorage.setItem(STARTED_KEY, String(Date.now()));
  } catch {
    // Without storage the duration is unknown; the step itself is still recorded.
  }
  trackPublicEvent("sign_in_started");
}

export function trackSignInFailed(reason: string) {
  takeStartedAt();
  trackPublicEvent("sign_in_failed", { reason: reason.slice(0, 80) });
}

/** Call once the app knows whether the person is signed in after loading. */
export function trackSignInReturn(signedIn: boolean) {
  const providerError = signInErrorFromUrl(window.location);
  const startedAt = takeStartedAt();
  if (providerError) {
    trackPublicEvent("sign_in_failed", { reason: providerError });
  } else if (startedAt !== null && signedIn) {
    trackAppEvent("sign_in_succeeded", { duration_ms: Math.max(0, Date.now() - startedAt) }, { page: "sign_in" });
  } else if (startedAt !== null) {
    trackPublicEvent("sign_in_abandoned", { duration_ms: Math.max(0, Date.now() - startedAt) });
  }
}

function takeStartedAt() {
  try {
    const value = window.sessionStorage.getItem(STARTED_KEY);
    window.sessionStorage.removeItem(STARTED_KEY);
    return value ? Number(value) : null;
  } catch {
    return null;
  }
}
