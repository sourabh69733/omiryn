// Match pools: the operator's page. Pure renderers that turn the API's pool list and pool view
// into HTML; main.js owns the fetches and the clicks. Private vibe areas never reach this page
// (the API strips them), and no score is ever shown as a percentage.

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const AREA_LABELS = {
  humor: "Humor", interests: "Interests", friend_wish: "Wants in a friend", daily_life: "Daily life", social_energy: "Social energy",
  keeping_in_touch: "Keeping in touch", conflict: "Conflict", values: "Values", stories: "Stories", accepts: "Accepts", deal_breakers: "Deal-breakers",
};
const FACT_LABELS = { area: "where they live", free_time: "when they are free", food: "what they eat", budget: "how they spend" };

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function weekdayName(weekday) {
  return WEEKDAYS[((Number(weekday) % 7) + 7) % 7] || "weekly";
}

export function areaLabel(area) {
  return AREA_LABELS[area] || String(area || "").replaceAll("_", " ");
}

/** One line on what keeps a member from match day, in the operator's words. */
export function readinessLine(readiness) {
  if (!readiness) return "Unknown";
  if (readiness.ready) return "Ready";
  const parts = [];
  if (readiness.milestone && !["ready_to_match", "deep"].includes(readiness.milestone)) parts.push(`vibe at ${readiness.milestone.replaceAll("_", " ")}`);
  const missing = (readiness.facts?.missing || []).filter((id) => ["area", "free_time"].includes(id)).map((id) => FACT_LABELS[id] || id);
  if (missing.length) parts.push(`needs ${missing.join(" and ")}`);
  return parts.length ? parts.join(" · ") : "Not ready";
}

/** Pair status in plain words for the pill and the status select. */
export const PAIR_STATUSES = ["candidate", "proposed", "asked", "introduced", "met", "no_show", "declined", "still_talking", "expired"];

export function pairStatusLabel(status) {
  return {
    candidate: "Candidate", proposed: "Proposed", asked: "Asked, waiting", introduced: "Introduced", met: "Met",
    no_show: "No-show", declined: "Declined", still_talking: "Still talking", expired: "No answer in time",
  }[status] || String(status || "");
}

const PILL_CLASS = { candidate: "", proposed: "warning", asked: "warning", introduced: "active", met: "success", still_talking: "success", no_show: "failed", declined: "deleted", expired: "deleted" };

function pill(status) {
  return `<span class="status-pill ${PILL_CLASS[status] || ""}">${esc(pairStatusLabel(status))}</span>`;
}

/** A name for a member id, from the view's members. */
export function nameOf(view, userId) {
  const member = (view?.members || []).find((m) => m.user_id === userId);
  return member?.name || String(userId || "").slice(0, 8);
}

export function renderPoolList(pools, selectedId) {
  if (!pools?.length) return '<tr><td class="empty-row" colspan="4">No pools yet. Create one for a building or a batch.</td></tr>';
  return pools.map((pool) => `
    <tr class="pool-row ${pool.id === selectedId ? "is-selected" : ""}" data-pool-id="${esc(pool.id)}" tabindex="0" role="button" aria-label="Open ${esc(pool.name)}">
      <td><strong>${esc(pool.name)}</strong></td>
      <td><code class="mono">${esc(pool.join_code || "")}</code></td>
      <td>${esc(weekdayName(pool.match_weekday))}s</td>
      <td><small>${esc(pool.created_at ? new Date(pool.created_at).toLocaleDateString() : "")}</small></td>
    </tr>`).join("");
}

function memberLines(member) {
  const entries = Object.entries(member.lines || {});
  if (!entries.length) return '<small class="pool-muted">No shareable lines yet.</small>';
  return `<ul class="pool-lines">${entries.map(([area, text]) => `<li><span>${esc(areaLabel(area))}</span>${esc(text)}</li>`).join("")}</ul>`;
}

export function renderMembers(view) {
  const members = view?.members || [];
  if (!members.length) return '<div class="table-empty">Nobody has joined with the code yet.</div>';
  return members.map((member) => `
    <article class="request-card pool-member ${member.readiness?.ready ? "is-ready" : ""}">
      <div class="request-card-head">
        <div>
          <strong>${esc(member.name || "Unnamed")}</strong>
          <span class="pool-muted">${esc(member.city || "")}</span>
        </div>
        <span class="status-pill ${member.readiness?.ready ? "success" : "warning"}">${esc(readinessLine(member.readiness))}</span>
      </div>
      ${memberLines(member)}
    </article>`).join("");
}

function checkBlock(check) {
  if (!check) return '<p class="pool-muted">No check stored.</p>';
  const reasons = (check.reasons || []).map((r) => `<li>${esc(typeof r === "string" ? r : r.text || "")}</li>`).join("");
  return `
    <div class="pool-check">
      <div class="request-meta-row"><span class="status-pill ${check.fit === "yes" ? "success" : check.fit === "no" ? "failed" : "warning"}">Fit: ${esc(check.fit || "unknown")}</span><span>${esc(String(check.comparable?.length ?? 0))} areas compared</span></div>
      ${reasons ? `<ul class="pool-reasons">${reasons}</ul>` : ""}
      ${check.difference ? `<p><strong>Difference:</strong> ${esc(typeof check.difference === "string" ? check.difference : check.difference.text || "")}</p>` : ""}
      ${check.icebreaker ? `<p><strong>Starter:</strong> ${esc(check.icebreaker)}</p>` : ""}
      ${check.why_not ? `<p class="pool-muted"><strong>Why not:</strong> ${esc(check.why_not)}</p>` : ""}
    </div>`;
}

export function renderPairs(view) {
  const pairs = view?.pairs || [];
  if (!pairs.length) return '<div class="table-empty">No pairs proposed in this pool yet.</div>';
  return pairs.map((pair) => `
    <article class="request-card pool-pair" data-pair-id="${esc(pair.id)}">
      <div class="request-card-head">
        <div>
          <strong>${esc(nameOf(view, pair.user_a))} &amp; ${esc(nameOf(view, pair.user_b))}</strong>
          <span class="pool-muted">${esc(pair.created_at ? new Date(pair.created_at).toLocaleString() : "")}${pair.introduced_at ? ` · introduced ${esc(new Date(pair.introduced_at).toLocaleDateString())}` : ""}</span>
        </div>
        ${pill(pair.status)}
      </div>
      ${checkBlock(pair.check)}
      ${pair.plan ? `<p class="pool-plan"><strong>Plan:</strong> ${esc(pair.plan.place || "")}${pair.plan.when ? `, ${esc(pair.plan.when)}` : ""}</p>` : ""}
      ${pair.status === "proposed" ? `
        <div class="pool-ask-row">
          <button type="button" class="secondary-button" data-ask="${esc(pair.id)}">Ask both in chat</button>
          <span class="pool-muted">Omi asks each person if they want to meet. Or introduce them directly below.</span>
        </div>
        <form class="pool-introduce" data-pair-id="${esc(pair.id)}">
          <label>Place <input name="place" maxlength="160" placeholder="Blue Tokai, Sector 29" required></label>
          <label>When, in words <input name="when" maxlength="80" placeholder="Saturday 6 pm" required></label>
          <label>Exact time (optional) <input name="meet_at" type="datetime-local"></label>
          <button type="submit">Introduce both</button>
        </form>` : ""}
      <div class="pool-status-row">
        <label>Status
          <select data-pair-status="${esc(pair.id)}">
            ${PAIR_STATUSES.map((s) => `<option value="${s}" ${s === pair.status ? "selected" : ""}>${esc(pairStatusLabel(s))}</option>`).join("")}
          </select>
        </label>
      </div>
    </article>`).join("");
}

export function renderSuggestions(view) {
  const suggestions = view?.suggestions || [];
  if (!suggestions.length) {
    const ready = view?.ready_count ?? 0;
    return `<div class="table-empty">${ready < 2 ? `${ready} ready. Pairs need at least two ready members.` : "Every ready pair has been proposed."}</div>`;
  }
  return suggestions.map((s, i) => `
    <div class="pool-suggestion">
      <span class="pool-suggestion-rank">${i + 1}</span>
      <div><strong>${esc(nameOf(view, s.user_a))} &amp; ${esc(nameOf(view, s.user_b))}</strong><span class="pool-muted">${esc(String(s.comparable ?? 0))} areas compared</span></div>
      <button type="button" class="secondary-button" data-propose="${esc(s.user_a)}|${esc(s.user_b)}">Propose</button>
    </div>`).join("");
}

export function renderPoolView(view) {
  if (!view) return "";
  const pool = view.pool || {};
  return `
    <div class="panel-heading">
      <div>
        <p class="eyebrow">Pool</p>
        <h2>${esc(pool.name || "")}</h2>
        <p class="pool-muted">Join code <code class="mono">${esc(pool.join_code || "")}</code> · matches on ${esc(weekdayName(pool.match_weekday))}s · ${esc(String(view.members?.length ?? 0))} members, ${esc(String(view.ready_count ?? 0))} ready</p>
      </div>
      <button type="button" data-pick="${esc(pool.id)}" ${(view.ready_count ?? 0) < 2 ? "disabled" : ""}>Pick this week's pairs</button>
    </div>
    <div id="pool-pick-result"></div>
    <div class="pool-columns">
      <section>
        <h3>Suggested pairs</h3>
        <p class="pool-muted">Ready members only, best first. Propose runs the compatibility check (one model call) and stores the pair. Nothing reaches a resident until you introduce them.</p>
        <div id="pool-suggestions">${renderSuggestions(view)}</div>
      </section>
      <section>
        <h3>Pairs so far</h3>
        <div class="request-list" id="pool-pairs">${renderPairs(view)}</div>
      </section>
    </div>
    <section>
      <h3>Members</h3>
      <div class="request-list pool-members" id="pool-members">${renderMembers(view)}</div>
    </section>`;
}

/** What a pick run did, in a few lines: pairs made, who waits, who was dropped and why. */
export function renderPickResult(result, view) {
  if (!result) return "";
  const names = (ids) => (ids || []).map((id) => esc(nameOf(view, id))).join(", ");
  const pairs = (result.pairs || []).map((pair) => `<li><strong>${esc(nameOf(view, pair.user_a))} &amp; ${esc(nameOf(view, pair.user_b))}</strong> · fit ${esc(pair.fit || "unknown")}</li>`).join("");
  const dropped = (result.dropped || []).map((pair) => `<li>${esc(nameOf(view, pair.user_a))} &amp; ${esc(nameOf(view, pair.user_b))}: ${esc(pair.why || "")}</li>`).join("");
  return `
    <div class="request-card pool-pick-result">
      <strong>Pick done: ${esc(String(result.pairs?.length || 0))} pairs proposed, ${esc(String(result.judged || 0))} checks run.</strong>
      ${pairs ? `<ul class="pool-reasons">${pairs}</ul>` : ""}
      ${result.group?.length ? `<p>Group of three: ${names(result.group)}</p>` : ""}
      ${result.waiting?.length ? `<p class="pool-muted">Waiting: ${names(result.waiting)}</p>` : ""}
      ${result.busy?.length ? `<p class="pool-muted">Already in a pair: ${names(result.busy)}</p>` : ""}
      ${dropped ? `<p class="pool-muted">Dropped:</p><ul class="pool-reasons">${dropped}</ul>` : ""}
    </div>`;
}
