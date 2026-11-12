// Small shared helpers for the admin pages: escaping, number and time formats, pills, cards,
// tables and inline SVG charts. Pure functions that return HTML strings, so they are easy to test.

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const numberFormat = new Intl.NumberFormat("en-IN");
const compactFormat = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export function num(value) {
  return numberFormat.format(Number(value || 0));
}

export function compact(value) {
  const n = Number(value || 0);
  return Math.abs(n) < 10000 ? num(n) : compactFormat.format(n);
}

/** Dollars with enough digits to be useful at tiny amounts, without six zeros at large ones. */
export function usd(value) {
  const n = Number(value || 0);
  if (n === 0) return "$0";
  if (Math.abs(n) >= 100) return `$${n.toFixed(0)}`;
  if (Math.abs(n) >= 1) return `$${n.toFixed(2)}`;
  if (Math.abs(n) >= 0.01) return `$${n.toFixed(3)}`;
  if (Math.abs(n) < 0.0001) return "<$0.0001";
  return `$${n.toFixed(4)}`;
}

export function pct(part, whole) {
  const p = Number(part || 0);
  const w = Number(whole || 0);
  if (!w) return "0%";
  const value = (p / w) * 100;
  return `${value < 10 && value > 0 ? value.toFixed(1) : Math.round(value)}%`;
}

export function ms(value) {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}s` : `${Math.round(n)}ms`;
}

export function shortId(value) {
  const text = String(value || "");
  return text.length > 10 ? text.slice(0, 8) : text;
}

export function titleize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replaceAll(".", " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1));
}

/** "3 min ago", "yesterday", "12 Oct". Absolute time stays in the title attribute. */
export function ago(value, now = Date.now()) {
  if (!value) return "never";
  const date = new Date(value);
  const time = date.getTime();
  if (Number.isNaN(time)) return "-";
  const seconds = Math.round((now - time) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: days > 300 ? "numeric" : undefined });
}

export function when(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function timeTag(value) {
  if (!value) return '<span class="muted">never</span>';
  return `<time datetime="${esc(value)}" title="${esc(when(value))}">${esc(ago(value))}</time>`;
}

export function dayLabel(isoDate) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** Change against the previous period as a small arrow chip. `goodWhenUp` flips the colour for costs and failures. */
export function delta(current, previous, { goodWhenUp = true } = {}) {
  const c = Number(current || 0);
  const p = Number(previous || 0);
  if (!p && !c) return '<span class="delta flat">no change</span>';
  if (!p) return `<span class="delta ${goodWhenUp ? "up" : "down"}">new</span>`;
  const change = Math.round(((c - p) / p) * 100);
  if (change === 0) return '<span class="delta flat">same as last week</span>';
  const better = change > 0 === goodWhenUp;
  return `<span class="delta ${better ? "up" : "down"}">${change > 0 ? "▲" : "▼"} ${Math.abs(change)}% vs last week</span>`;
}

const PILL_TONES = {
  good: ["success", "done", "completed", "active", "met", "still_talking", "ok", "passed", "good", "web"],
  bad: ["failed", "error", "client_error", "bad", "harmful", "deleted", "declined", "no_show"],
  warn: ["pending", "running", "open", "proposed", "asked", "off", "warning", "temporary"],
};

export function pill(value, label) {
  const text = String(value ?? "unknown");
  const tone = Object.entries(PILL_TONES).find(([, values]) => values.includes(text.toLowerCase()))?.[0] || "neutral";
  return `<span class="pill ${tone}">${esc(label ?? titleize(text))}</span>`;
}

export function stat({ label, value, sub = "", tone = "", href = "" }) {
  const body = `
    <span class="stat-label">${esc(label)}</span>
    <strong class="stat-value">${value}</strong>
    ${sub ? `<span class="stat-sub">${sub}</span>` : ""}`;
  return href
    ? `<a class="stat ${tone}" href="${esc(href)}" data-link>${body}</a>`
    : `<div class="stat ${tone}">${body}</div>`;
}

export function panel({ title, kicker = "", actions = "", body, className = "" }) {
  return `
    <section class="panel ${className}">
      <header class="panel-head">
        <div>${kicker ? `<p class="kicker">${esc(kicker)}</p>` : ""}<h2>${esc(title)}</h2></div>
        ${actions ? `<div class="panel-actions">${actions}</div>` : ""}
      </header>
      <div class="panel-body">${body}</div>
    </section>`;
}

export function empty(message, tone = "") {
  return `<div class="empty ${tone}">${esc(message)}</div>`;
}

/** A table from column specs: {label, cell(row) -> html, className?, align?}. */
export function table(columns, rows, { emptyText = "Nothing here yet.", rowAttrs = () => "" } = {}) {
  if (!rows?.length) return empty(emptyText);
  const head = columns.map((col) => `<th class="${col.align === "right" ? "num" : ""}">${esc(col.label)}</th>`).join("");
  const body = rows
    .map(
      (row) =>
        `<tr ${rowAttrs(row)}>${columns
          .map((col) => `<td class="${[col.align === "right" ? "num" : "", col.className || ""].join(" ").trim()}">${col.cell(row)}</td>`)
          .join("")}</tr>`,
    )
    .join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/** Key/value rows for small facts. */
export function facts(entries) {
  return `<dl class="facts">${entries
    .filter(Boolean)
    .map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${value}</dd></div>`)
    .join("")}</dl>`;
}

/**
 * Daily bars as inline SVG. `series` is [{key, label, tone}]; the first is the bar, a second one
 * (like failures) is drawn as a stacked cap in its own colour. Each bar has a native tooltip.
 */
export function barChart(days, series, { format = num, height = 132 } = {}) {
  if (!days?.length) return empty("No data for this period.");
  const [main, extra] = series;
  const totals = days.map((day) => Number(day[main.key] || 0) + (extra ? Number(day[extra.key] || 0) : 0));
  const max = Math.max(...totals, 0);
  const width = 640;
  const pad = { top: 8, bottom: 22, left: 0, right: 0 };
  const plot = height - pad.top - pad.bottom;
  const step = width / days.length;
  const barWidth = Math.max(2, Math.min(28, step * 0.62));
  const labelEvery = Math.ceil(days.length / 7);
  const bars = days
    .map((day, index) => {
      const mainValue = Number(day[main.key] || 0);
      const extraValue = extra ? Number(day[extra.key] || 0) : 0;
      const x = index * step + (step - barWidth) / 2;
      const mainHeight = max ? (mainValue / max) * plot : 0;
      const extraHeight = max ? (extraValue / max) * plot : 0;
      const baseY = pad.top + plot;
      const tip = `${dayLabel(day.date)}: ${main.label} ${format(mainValue)}${extra ? `, ${extra.label} ${format(extraValue)}` : ""}`;
      const label =
        index % labelEvery === 0 || index === days.length - 1
          ? `<text x="${x + barWidth / 2}" y="${height - 6}" text-anchor="middle">${esc(dayLabel(day.date))}</text>`
          : "";
      return `<g class="bar-group"><title>${esc(tip)}</title>
        <rect class="bar-hit" x="${index * step}" y="${pad.top}" width="${step}" height="${plot}"></rect>
        ${mainValue || !extraValue ? `<rect class="bar ${main.tone || ""}" x="${x}" y="${baseY - mainHeight}" width="${barWidth}" height="${Math.max(mainValue ? 1.5 : 0, mainHeight)}" rx="2"></rect>` : ""}
        ${extraValue ? `<rect class="bar ${extra.tone || "bad"}" x="${x}" y="${baseY - mainHeight - extraHeight}" width="${barWidth}" height="${Math.max(1.5, extraHeight)}" rx="2"></rect>` : ""}
        ${label}</g>`;
    })
    .join("");
  const legend = series
    .map((s) => `<span class="legend-item"><i class="swatch ${s.tone || ""}"></i>${esc(s.label)}</span>`)
    .join("");
  return `<figure class="chart">
    <div class="chart-meta"><span class="chart-max">max ${esc(format(max))}/day</span><span class="legend">${legend}</span></div>
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(main.label)} per day">
      <line class="axis" x1="0" x2="${width}" y1="${pad.top + plot}" y2="${pad.top + plot}"></line>
      ${bars}
    </svg></figure>`;
}

/** Horizontal share bars for a breakdown, like memories by kind. */
export function shareBars(rows, { label, value, format = num }) {
  if (!rows?.length) return empty("Nothing yet.");
  const max = Math.max(...rows.map((row) => Number(value(row) || 0)), 1);
  return `<ul class="share-bars">${rows
    .map((row) => {
      const v = Number(value(row) || 0);
      return `<li><span class="share-label">${label(row)}</span><span class="share-track"><i style="width:${(v / max) * 100}%"></i></span><span class="share-value">${esc(format(v))}</span></li>`;
    })
    .join("")}</ul>`;
}

export function skeleton(blocks = 3) {
  return `<div class="skeleton-grid">${'<div class="skeleton"></div>'.repeat(blocks)}</div>`;
}

export function apiErrorMessage(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || item.message || String(item)).join(", ");
  return fallback;
}

export function personName(person) {
  return person?.display_name || person?.profile?.display_name || `User ${shortId(person?.user_id)}`;
}

export function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("") || "?";
}
