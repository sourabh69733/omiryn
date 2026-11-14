// Experience tracking in the signed-in app: time on each page, page speed, and rage clicks.
// Sends names, numbers and code-level labels only, never what was typed or shown.
import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from "web-vitals";

import { trackAppEvent, trackPageView } from "./appLogger";
import { ActiveTimer, RageClickDetector, describeTarget } from "./experienceMetrics";

// Visits shorter than this are not worth an event (a page flashed past on the way somewhere).
const MIN_VISIT_MS = 500;

let currentPage: string | null = null;
let timer: ActiveTimer | null = null;
let initialized = false;

export function initExperienceTracking() {
  if (initialized) return;
  initialized = true;
  const interact = () => timer?.interact(performance.now());
  for (const name of ["pointerdown", "keydown", "wheel", "touchstart"] as const) {
    window.addEventListener(name, interact, { passive: true, capture: true });
  }
  window.addEventListener("scroll", interact, { passive: true, capture: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") endVisit("hidden");
    else if (currentPage) timer = new ActiveTimer(performance.now());
  });
  window.addEventListener("pagehide", () => endVisit("closed"));
  watchRageClicks();
  watchPageSpeed();
}

/** Call on every page change: closes the visit to the last page and starts one on this page. */
export function enterPage(page: string) {
  if (page === currentPage) return;
  endVisit("navigate");
  currentPage = page;
  timer = new ActiveTimer(performance.now(), document.visibilityState === "visible");
  trackPageView(page);
}

function endVisit(reason: "navigate" | "hidden" | "closed") {
  if (!currentPage || !timer) return;
  const { activeMs, visibleMs } = timer.read(performance.now());
  timer = null;
  if (visibleMs < MIN_VISIT_MS) return;
  trackAppEvent("page_left", { active_ms: activeMs, visible_ms: visibleMs, reason }, { page: currentPage });
}

function watchRageClicks() {
  const detector = new RageClickDetector();
  window.addEventListener(
    "click",
    (event) => {
      if (detector.click(event.clientX, event.clientY, event.timeStamp)) {
        trackAppEvent("rage_click", { target: describeTarget(event.target as Element | null) }, { page: currentPage || undefined });
      }
    },
    { capture: true, passive: true },
  );
}

function watchPageSpeed() {
  const report = (metric: Metric) => {
    const value = metric.name === "CLS" ? Math.round(metric.value * 1000) / 1000 : Math.round(metric.value);
    trackAppEvent(
      "page_speed",
      { metric: metric.name, value, rating: metric.rating, nav_type: metric.navigationType },
      { page: currentPage || undefined },
    );
  };
  onTTFB(report);
  onFCP(report);
  onLCP(report);
  onINP(report);
  onCLS(report);
}
