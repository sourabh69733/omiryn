// Growth: how new people get started, whether they come back, and how matches turn out.
import { dayLabel, empty, esc, funnel, num, panel, pct, skeleton, stat } from "../ui.js";

export async function render({ root, api, isCurrent }) {
  root.innerHTML = skeleton(6);
  const data = await api("/api/admin/growth?weeks=8");
  if (!isCurrent()) return;
  root.innerHTML = view(data);
}

export function minutes(value) {
  if (value === null || value === undefined) return "-";
  return value < 1 ? "under a minute" : `${num(value)} min`;
}

/** One cell of the cohort table, shaded by how many came back. */
export function cohortCell(share) {
  if (share === null || share === undefined) return '<td class="cohort-cell future"></td>';
  const level = Math.min(5, Math.ceil(share * 5));
  return `<td class="cohort-cell level-${level}">${pct(share, 1)}</td>`;
}

function cohortTable(cohorts) {
  if (!cohorts?.some((cohort) => cohort.users)) return empty("Nobody has joined in these weeks yet.");
  const width = Math.max(...cohorts.map((cohort) => cohort.active_share_by_week.length));
  const head = Array.from({ length: width }, (_, index) => `<th class="num">${index === 0 ? "Week 1" : `+${index}`}</th>`).join("");
  const rows = cohorts
    .map(
      (cohort) => `<tr><td>${esc(dayLabel(cohort.week_start))}</td><td class="num">${num(cohort.users)}</td>${
        cohort.users ? cohort.active_share_by_week.map(cohortCell).join("") : `<td colspan="${width}" class="muted">no one joined</td>`
      }</tr>`,
    )
    .join("");
  return `<div class="table-wrap"><table class="cohorts"><thead><tr><th>Joined week of</th><th class="num">People</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function view(data) {
  const returns = data.returns || [];
  const start = data.getting_started || {};
  const secondWeek = start.second_week || {};
  const matching = data.matching || {};

  return `
    <div class="stats">
      ${returns
        .map((row) =>
          stat({
            label: row.label,
            value: row.eligible ? pct(row.returned, row.eligible) : "-",
            sub: row.eligible ? `${num(row.returned)} of ${num(row.eligible)} people` : "nobody has joined long enough ago",
          }),
        )
        .join("")}
      ${stat({ label: "Time to Omi's first reply", value: minutes(start.minutes_to_first_reply_p50), sub: "typical, from first visit" })}
    </div>
    <div class="grid two">
      ${panel({
        title: "Getting started",
        kicker: `Last ${start.days || 30} days`,
        body: `${funnel(start.steps)}
          <p class="muted small-note">Of new people who joined at least two weeks ago, ${num(secondWeek.returned)} of ${num(secondWeek.eligible)} were active in their second week.</p>`,
      })}
      ${panel({
        title: "Matching",
        kicker: "All pairs so far",
        body: `${funnel(matching.steps)}
          <p class="muted small-note">Declined ${num(matching.declined)} · no answer in time ${num(matching.expired)} · no-show ${num(matching.no_show)}</p>`,
      })}
    </div>
    ${panel({
      title: "Coming back, by the week people joined",
      kicker: "Share active in each week after joining",
      body: cohortTable(data.cohorts),
    })}
    <p class="footnote">Active means the person opened the app, sent a message, or got a reply. The first two getting-started steps count browser sessions, the rest count people.</p>`;
}
