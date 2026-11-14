// Pure pieces of experience tracking, kept apart from the browser wiring so they can be tested.

/** Time without any input after which a person counts as away, not reading. */
export const IDLE_MS = 30_000;

/**
 * Active time on one page: time the tab is visible, counting at most IDLE_MS after each input,
 * so a tab left open overnight adds 30 seconds, not 8 hours.
 */
export class ActiveTimer {
  private activeMs = 0;
  private visibleMs = 0;
  private lastInput: number;
  private visibleSince: number | null;

  constructor(now: number, visible = true) {
    this.lastInput = now;
    this.visibleSince = visible ? now : null;
  }

  interact(now: number) {
    if (this.visibleSince === null) return;
    this.activeMs += Math.min(now - this.lastInput, IDLE_MS);
    this.lastInput = now;
  }

  hide(now: number) {
    if (this.visibleSince === null) return;
    this.interact(now);
    this.visibleMs += now - this.visibleSince;
    this.visibleSince = null;
  }

  show(now: number) {
    if (this.visibleSince !== null) return;
    this.visibleSince = now;
    this.lastInput = now;
  }

  read(now: number) {
    const open = this.visibleSince !== null;
    return {
      activeMs: Math.round(this.activeMs + (open ? Math.min(now - this.lastInput, IDLE_MS) : 0)),
      visibleMs: Math.round(this.visibleMs + (open ? now - (this.visibleSince as number) : 0)),
    };
  }
}

const RAGE_CLICKS = 3;
const RAGE_WINDOW_MS = 800;
const RAGE_RADIUS_PX = 24;

/** Three or more clicks within 800 ms in one small spot: something looked clickable and did nothing. */
export class RageClickDetector {
  private clicks: { x: number; y: number; at: number }[] = [];

  click(x: number, y: number, at: number) {
    this.clicks = this.clicks.filter(
      (click) => at - click.at <= RAGE_WINDOW_MS && Math.hypot(click.x - x, click.y - y) <= RAGE_RADIUS_PX,
    );
    this.clicks.push({ x, y, at });
    if (this.clicks.length < RAGE_CLICKS) return false;
    this.clicks = [];
    return true;
  }
}

/** A code-only name for what was clicked: tag and first class, never its text. "button.send-button" */
export function describeTarget(element: { tagName?: string; classList?: { length: number; [index: number]: string } } | null) {
  if (!element?.tagName) return "unknown";
  const tag = element.tagName.toLowerCase();
  const firstClass = element.classList && element.classList.length ? element.classList[0] : "";
  return (firstClass ? `${tag}.${firstClass}` : tag).slice(0, 80);
}

/** Supabase sends a failed sign-in back with ?error= or #error= (and error_code); keep only the code. */
export function signInErrorFromUrl(location: { search: string; hash: string }) {
  for (const raw of [location.search, location.hash.replace(/^#/, "")]) {
    const params = new URLSearchParams(raw);
    const code = params.get("error_code") || params.get("error");
    if (code) return code.replace(/[^a-z0-9_]+/gi, "_").slice(0, 80);
  }
  return null;
}
