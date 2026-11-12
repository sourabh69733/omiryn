import { barChart, compact, empty, esc, ms, num, panel, pct, pill, shortId, skeleton, stat, table, timeTag, titleize, usd } from "../ui.js";

const RANGES = [7, 30, 90];
let days = 30;

export async function render({ root, api, isCurrent }) {
  root.innerHTML = skeleton(6);
  const data = await api(`/api/admin/costs?days=${days}`);
  if (!isCurrent()) return;
  root.innerHTML = view(data);
  root.querySelector(".range").addEventListener("click", (event) => {
    const button = event.target.closest("[data-days]");
    if (!button) return;
    days = Number(button.dataset.days);
    void render({ root, api, isCurrent });
  });
}

export function kindLabel(kind) {
  const labels = {
    chat_reply: "Omi reply",
    background_cognition: "Memory (background)",
    memory_shadow_extract: "Memory (shadow)",
    memory_embedding_query: "Memory search",
    memory_embedding_index: "Memory indexing",
    chat_embedding_index: "Chat indexing",
    profile_fact_extract: "Profile facts",
    reply_request_check: "Reply check",
    input_guardrail: "Input check",
    eval_judge: "Eval judge",
  };
  return labels[kind] || titleize(kind || "call");
}

export function view(data) {
  const t = data.totals || {};
  const latency = data.reply_latency || {};
  const range = `<div class="range" role="group" aria-label="Range">${RANGES.map(
    (value) => `<button type="button" class="chip" data-days="${value}" aria-pressed="${value === data.days}">${value} days</button>`,
  ).join("")}</div>`;

  return `
    <div class="page-tools">${range}</div>
    <div class="stats">
      ${stat({ label: "Spend", value: usd(t.cost), sub: `${usd((t.cost || 0) / Math.max(1, data.days))} a day on average` })}
      ${stat({ label: "Cost per reply", value: t.replies ? usd((t.cost || 0) / t.replies) : "-", sub: "all model calls ÷ Omi replies" })}
      ${stat({ label: "Model calls", value: num(t.calls), sub: `${num(t.replies)} were Omi replies` })}
      ${stat({ label: "Failures", value: num(t.failed), sub: `${pct(t.failed, t.calls)} of calls`, tone: t.failed ? "warn" : "" })}
      ${stat({ label: "Tokens", value: compact(t.tokens), sub: `${compact(t.prompt_tokens)} in · ${compact(t.completion_tokens)} out` })}
      ${stat({ label: "Reply speed", value: ms(latency.p50_ms), sub: latency.samples ? `slowest 5%: ${ms(latency.p95_ms)} · max ${ms(latency.max_ms)}` : "no replies" })}
    </div>
    <div class="grid two">
      ${panel({ title: "Spend per day", kicker: `Last ${data.days} days`, body: barChart(data.daily, [{ key: "cost_usd", label: "Cost", tone: "alt" }], { format: usd }) })}
      ${panel({
        title: "Calls per day",
        kicker: `Last ${data.days} days`,
        body: barChart(
          data.daily.map((day) => ({ ...day, ok: day.calls - day.failed })),
          [
            { key: "ok", label: "Worked" },
            { key: "failed", label: "Failed", tone: "bad" },
          ],
        ),
      })}
    </div>
    <div class="grid two">
      ${panel({
        title: "By kind of work",
        kicker: "Where the money goes",
        body: table(
          [
            { label: "Kind", cell: (r) => `${esc(kindLabel(r.request_kind))}<small class="mono">${esc(r.request_kind)}</small>` },
            { label: "Calls", align: "right", cell: (r) => `${num(r.calls)}${r.failed ? `<small class="tone-bad">${num(r.failed)} failed</small>` : ""}` },
            { label: "Avg time", align: "right", cell: (r) => ms(r.avg_latency_ms) },
            { label: "Spend", align: "right", cell: (r) => `${usd(r.cost_usd)}<small>${pct(r.cost_usd, t.cost)}</small>` },
          ],
          data.by_kind,
          { emptyText: "No calls in this period." },
        ),
      })}
      ${panel({
        title: "By model",
        kicker: "Providers",
        body: table(
          [
            { label: "Model", cell: (r) => `<span class="wrap">${esc(r.model || "-")}</span><small>${esc(r.provider || "")}</small>` },
            { label: "Calls", align: "right", cell: (r) => `${num(r.calls)}${r.failed ? `<small class="tone-bad">${num(r.failed)} failed</small>` : ""}` },
            { label: "Tokens", align: "right", cell: (r) => compact(r.tokens) },
            { label: "Spend", align: "right", cell: (r) => usd(r.cost_usd) },
          ],
          data.by_model,
          { emptyText: "No calls in this period." },
        ),
      })}
    </div>
    ${panel({
      title: "Recent failures",
      kicker: `Last ${data.days} days`,
      body: data.recent_failures?.length
        ? `<ul class="error-list">${data.recent_failures
            .map(
              (row) => `<li><div><strong>${esc(kindLabel(row.request_kind))}</strong> <span class="muted">${esc(row.model || "")}</span>
              ${row.user_id ? `<a class="mono" href="/users/${encodeURIComponent(row.user_id)}" data-link>${esc(shortId(row.user_id))}</a>` : ""}</div>
              <code class="error-text">${esc(row.error || "No error text")}</code>${timeTag(row.created_at)}</li>`,
            )
            .join("")}</ul>`
        : empty("No failures. 🎉"),
    })}
    ${panel({
      title: "Latest model calls",
      kicker: "Ledger",
      body: table(
        [
          { label: "When", cell: (r) => timeTag(r.created_at) },
          { label: "Kind", cell: (r) => esc(kindLabel(r.request_kind)) },
          { label: "User", cell: (r) => (r.user_id ? `<a class="mono" href="/users/${encodeURIComponent(r.user_id)}" data-link>${esc(shortId(r.user_id))}</a>` : "-") },
          { label: "Model", cell: (r) => `<span class="wrap">${esc(r.model || "-")}</span>`, className: "hide-narrow" },
          { label: "Tokens", align: "right", cell: (r) => num(r.tokens) },
          { label: "Time", align: "right", cell: (r) => ms(r.latency_ms) },
          { label: "Cost", align: "right", cell: (r) => usd(r.cost_usd) },
          { label: "", cell: (r) => (r.success ? pill("ok", "OK") : pill("failed")) },
        ],
        data.recent_calls,
        { emptyText: "No calls yet." },
      ),
    })}`;
}
