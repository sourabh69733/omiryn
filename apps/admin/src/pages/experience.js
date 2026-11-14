// Experience: does sign-in work, how fast are pages and API calls, where people spend time, what breaks.
import { barChart, empty, esc, ms, num, panel, pct, pill, shareBars, skeleton, stat, table, timeTag, titleize } from "../ui.js";

const RANGES = [1, 7, 30];
let days = 7;

// Google's Web Vitals limits: at or under the first is good, over the second is poor.
export const SPEED_LIMITS = {
  LCP: [2500, 4000],
  INP: [200, 500],
  CLS: [0.1, 0.25],
  FCP: [1800, 3000],
  TTFB: [800, 1800],
};
const SPEED_LABELS = { LCP: "Main content shown", INP: "Response to taps", CLS: "Layout jumps", FCP: "First paint", TTFB: "Server first byte" };

export async function render({ root, api, isCurrent }) {
  root.innerHTML = skeleton(6);
  const data = await api(`/api/admin/experience?days=${days}`);
  if (!isCurrent()) return;
  root.innerHTML = view(data);
  root.querySelector(".range").addEventListener("click", (event) => {
    const button = event.target.closest("[data-days]");
    if (!button) return;
    days = Number(button.dataset.days);
    void render({ root, api, isCurrent });
  });
}

export function speedTone(metric, value) {
  const [good, poor] = SPEED_LIMITS[metric] || [];
  if (value == null || good == null) return "neutral";
  return value <= good ? "good" : value > poor ? "bad" : "warn";
}

function speedCell(metric, entry) {
  if (!entry) return '<span class="muted">-</span>';
  const value = metric === "CLS" ? entry.p75.toFixed(2) : ms(entry.p75);
  return `${pill(speedTone(metric, entry.p75), value)}<small>${num(entry.samples)} loads</small>`;
}

function upTo(value) {
  return value == null ? "-" : `≤ ${ms(value)}`;
}

export function view(data) {
  const signIn = data.sign_in || {};
  const apiTiming = data.api || {};
  const errors = data.errors || [];
  const errorCount = errors.reduce((sum, error) => sum + error.count, 0);
  const rageCount = (data.rage_clicks || []).reduce((sum, row) => sum + row.count, 0);
  const range = `<div class="range" role="group" aria-label="Range">${RANGES.map(
    (value) => `<button type="button" class="chip" data-days="${value}" aria-pressed="${value === data.days}">${value === 1 ? "Today" : `${value} days`}</button>`,
  ).join("")}</div>`;

  return `
    <div class="page-tools">${range}</div>
    <div class="stats">
      ${stat({ label: "Sign-in success", value: signIn.started ? pct(signIn.succeeded, signIn.started) : "-", sub: `${num(signIn.succeeded)} of ${num(signIn.started)} who started`, tone: signIn.started && signIn.success_rate < 0.8 ? "warn" : "" })}
      ${stat({ label: "Sign-in failures", value: num(signIn.failed), sub: `${num(signIn.abandoned)} came back without signing in`, tone: signIn.failed ? "bad" : "" })}
      ${stat({ label: "Time to sign in", value: ms(signIn.duration_p50_ms), sub: signIn.duration_p90_ms ? `slowest 10%: ${ms(signIn.duration_p90_ms)}` : "no sign-ins yet" })}
      ${stat({ label: "API speed", value: upTo(apiTiming.p50_ms), sub: `slowest 5%: ${upTo(apiTiming.p95_ms)} · ${num(apiTiming.calls)} calls` })}
      ${stat({ label: "Server errors", value: num(apiTiming.server_errors), sub: `${pct(apiTiming.server_errors, apiTiming.calls)} of calls`, tone: apiTiming.server_errors ? "bad" : "" })}
      ${stat({ label: "App errors", value: num(errorCount), sub: `${num(errors.length)} different kinds`, tone: errorCount ? "warn" : "" })}
      ${stat({ label: "Rage clicks", value: num(rageCount), sub: "3 quick clicks in one spot", tone: rageCount ? "warn" : "" })}
    </div>
    <div class="grid two">
      ${panel({
        title: "Sign-in",
        kicker: "Per day",
        body: `${barChart(
          (signIn.daily || []).map((day) => ({ ...day, ok: day.succeeded })),
          [
            { key: "ok", label: "Signed in" },
            { key: "failed", label: "Failed", tone: "bad" },
          ],
        )}
        ${signIn.failures?.length ? `<ul class="reason-list">${signIn.failures.map((row) => `<li><code>${esc(row.reason)}</code><span>${num(row.count)}</span></li>`).join("")}</ul>` : '<p class="muted small-note">No failed sign-ins.</p>'}`,
      })}
      ${panel({
        title: "Where time goes",
        kicker: "Active time by page",
        body: shareBars(data.pages || [], { label: (row) => esc(titleize(row.page)), value: (row) => Math.round(row.share * 1000) / 10, format: (value) => `${value}%` }),
      })}
    </div>
    ${panel({
      title: "Pages",
      kicker: "Visits, time and quick exits",
      body: table(
        [
          { label: "Page", cell: (row) => esc(titleize(row.page)) },
          { label: "Share of time", align: "right", cell: (row) => pct(row.share, 1) },
          { label: "Visits", align: "right", cell: (row) => num(row.visits) },
          { label: "Users", align: "right", cell: (row) => num(row.users) },
          { label: "Typical visit", align: "right", cell: (row) => ms(row.median_visit_ms) },
          { label: "Left within 5s", align: "right", cell: (row) => (row.quick_exit_rate >= 0.4 ? `<span class="tone-bad">${pct(row.quick_exit_rate, 1)}</span>` : pct(row.quick_exit_rate, 1)) },
        ],
        data.pages,
        { emptyText: "No page visits recorded yet. They appear once people use the new web build." },
      ),
    })}
    ${panel({
      title: "Page speed",
      kicker: "75% of loads were at or under",
      body: table(
        [
          { label: "Page", cell: (row) => (row.page === "all" ? "<strong>All pages</strong>" : esc(titleize(row.page))) },
          ...Object.keys(SPEED_LIMITS).map((metric) => ({
            label: SPEED_LABELS[metric],
            cell: (row) => speedCell(metric, row.metrics[metric]),
            className: metric === "TTFB" || metric === "FCP" ? "hide-narrow" : "",
          })),
        ],
        data.speed?.overall && Object.keys(data.speed.overall.metrics).length ? [data.speed.overall, ...data.speed.pages] : [],
        { emptyText: "No speed readings yet." },
      ),
    })}
    ${panel({
      title: "Slowest API calls",
      kicker: "Server time to first byte",
      body: table(
        [
          { label: "Call", cell: (row) => `<code>${esc(row.method)} ${esc(row.route)}</code>` },
          { label: "Calls", align: "right", cell: (row) => num(row.calls) },
          { label: "Typical", align: "right", cell: (row) => upTo(row.p50_ms) },
          { label: "Slowest 5%", align: "right", cell: (row) => upTo(row.p95_ms) },
          { label: "Max", align: "right", cell: (row) => ms(row.max_ms), className: "hide-narrow" },
          { label: "Errors", align: "right", cell: (row) => (row.server_errors ? `<span class="tone-bad">${num(row.server_errors)}</span>` : "0") },
        ],
        (apiTiming.routes || []).slice(0, 25),
        { emptyText: "No API timing yet. It is saved once a minute." },
      ),
    })}
    <div class="grid two">
      ${panel({
        title: "App errors",
        kicker: "Grouped by kind",
        body: errors.length
          ? `<ul class="error-list">${errors
              .map(
                (error) => `<li><div><strong>${esc(error.message_code)}</strong> <span class="muted">on ${esc(titleize(error.page))}${error.source ? ` · ${esc(error.source)}` : ""}</span></div>
                <span class="muted">${num(error.count)} times · ${num(error.users)} users${error.releases.length ? ` · release ${esc(error.releases.join(", "))}` : ""}</span>${timeTag(error.last_at)}</li>`,
              )
              .join("")}</ul>`
          : empty("No app errors. 🎉"),
      })}
      ${panel({
        title: "Rage clicks",
        kicker: "Something looked clickable",
        body: table(
          [
            { label: "Page", cell: (row) => esc(titleize(row.page)) },
            { label: "Element", cell: (row) => `<code>${esc(row.target)}</code>` },
            { label: "Times", align: "right", cell: (row) => num(row.count) },
            { label: "Users", align: "right", cell: (row) => num(row.users) },
          ],
          data.rage_clicks,
          { emptyText: "None." },
        ),
      })}
    </div>
    ${panel({
      title: "Releases",
      kicker: "Web builds seen",
      body: table(
        [
          { label: "Release", cell: (row) => `<code>${esc(row.release)}</code>` },
          { label: "First seen", cell: (row) => timeTag(row.first_seen) },
          { label: "Events", align: "right", cell: (row) => num(row.events) },
          { label: "App errors", align: "right", cell: (row) => (row.errors ? `<span class="tone-bad">${num(row.errors)}</span>` : "0") },
        ],
        data.releases,
        { emptyText: "No events yet." },
      ),
    })}`;
}
