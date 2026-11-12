import {
  barChart,
  empty,
  esc,
  facts,
  initials,
  num,
  panel,
  personName,
  pill,
  shareBars,
  shortId,
  skeleton,
  stat,
  table,
  timeTag,
  titleize,
  usd,
  when,
} from "../ui.js";

const DAY = 86400000;
const FILTERS = {
  all: { label: "All", test: () => true },
  active: { label: "Active this week", test: (p, now) => p.last_active_at && now - new Date(p.last_active_at) < 7 * DAY },
  quiet: { label: "Quiet 14+ days", test: (p, now) => !p.last_active_at || now - new Date(p.last_active_at) >= 14 * DAY },
  failures: { label: "Had failures", test: (p) => p.failed_replies > 0 },
  memories: { label: "No memories", test: (p) => !p.memories },
};
const SORTS = {
  last_active_at: { label: "Last active", value: (p) => p.last_active_at || "" },
  replies: { label: "Most replies", value: (p) => p.replies },
  replies_7d: { label: "Most replies this week", value: (p) => p.replies_7d },
  cost_usd: { label: "Highest spend", value: (p) => p.cost_usd },
  memories: { label: "Most memories", value: (p) => p.memories },
  joined_at: { label: "Newest", value: (p) => p.joined_at || "" },
};

const state = { people: null, search: "", filter: "all", sort: "last_active_at" };

export async function render({ root, api, params, quiet, isCurrent, navigate }) {
  const userId = params[0] || null;
  // Start the user's details at once; the list may need loading first.
  const personRequest = userId ? api(`/api/admin/people/${encodeURIComponent(userId)}`).then((data) => ({ data }), (error) => ({ error })) : null;
  if (!state.people || quiet || !root.querySelector(".people-layout")) {
    root.innerHTML = skeleton(4);
    const data = await api("/api/admin/people");
    if (!isCurrent()) return;
    state.people = data.people || [];
    root.innerHTML = layout();
    bind(root, navigate);
  }
  renderList(root, userId);
  const detail = root.querySelector("#person-detail");
  root.querySelector(".people-layout").classList.toggle("has-detail", Boolean(userId));
  if (!personRequest) {
    detail.innerHTML = "";
    return;
  }
  detail.innerHTML = `<div class="panel">${skeleton(3)}</div>`;
  const { data: person, error } = await personRequest;
  if (!isCurrent()) return;
  detail.innerHTML = error ? `<div class="panel">${empty(error.message, "bad")}</div>` : personView(person);
  if (!error) detail.scrollIntoView({ block: "nearest" });
}

function layout() {
  return `
    <div class="people-layout">
      <section class="panel people-list">
        <header class="panel-head toolbar">
          <input id="people-search" type="search" placeholder="Search name, place or id" value="${esc(state.search)}" aria-label="Search users">
          <select id="people-sort" aria-label="Sort users">${Object.entries(SORTS)
            .map(([key, sort]) => `<option value="${key}" ${key === state.sort ? "selected" : ""}>${esc(sort.label)}</option>`)
            .join("")}</select>
        </header>
        <div class="chips" role="group" aria-label="Filter users">${Object.entries(FILTERS)
          .map(([key, filter]) => `<button type="button" class="chip" data-filter="${key}" aria-pressed="${key === state.filter}">${esc(filter.label)} <span data-filter-count="${key}"></span></button>`)
          .join("")}</div>
        <div id="people-table"></div>
      </section>
      <aside id="person-detail" class="person-detail" aria-live="polite"></aside>
    </div>`;
}

function bind(root, navigate) {
  root.querySelector("#people-search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderList(root, currentId());
  });
  root.querySelector("#people-sort").addEventListener("change", (event) => {
    state.sort = event.target.value;
    renderList(root, currentId());
  });
  root.querySelector(".chips").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-filter]");
    if (!chip) return;
    state.filter = chip.dataset.filter;
    renderList(root, currentId());
  });
  root.querySelector("#people-table").addEventListener("click", (event) => {
    const row = event.target.closest("[data-user-id]");
    if (row && !event.target.closest("a")) navigate(`/users/${encodeURIComponent(row.dataset.userId)}`);
  });
  root.querySelector("#people-table").addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-user-id]");
    if (row && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      navigate(`/users/${encodeURIComponent(row.dataset.userId)}`);
    }
  });
  root.addEventListener("click", (event) => {
    const copy = event.target.closest("[data-copy]");
    if (!copy) return;
    navigator.clipboard?.writeText(copy.dataset.copy).then(() => {
      copy.textContent = "Copied";
      setTimeout(() => (copy.textContent = "Copy id"), 1200);
    });
  });
}

function currentId() {
  const match = /^\/users\/([^/]+)/.exec(window.location.pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

export function filterPeople(people, { search = "", filter = "all", sort = "last_active_at" } = {}, now = Date.now()) {
  const needle = search.trim().toLowerCase();
  const rows = people.filter(
    (person) =>
      FILTERS[filter].test(person, now) &&
      (!needle || [person.display_name, person.place, person.user_id].some((value) => String(value || "").toLowerCase().includes(needle))),
  );
  const value = SORTS[sort].value;
  return rows.sort((a, b) => (value(a) < value(b) ? 1 : value(a) > value(b) ? -1 : 0));
}

function renderList(root, selectedId) {
  const now = Date.now();
  root.querySelectorAll("[data-filter]").forEach((chip) => chip.setAttribute("aria-pressed", String(chip.dataset.filter === state.filter)));
  root.querySelectorAll("[data-filter-count]").forEach((badge) => {
    badge.textContent = String(state.people.filter((person) => FILTERS[badge.dataset.filterCount].test(person, now)).length);
  });
  const rows = filterPeople(state.people, state, now);
  root.querySelector("#people-table").innerHTML = table(
    [
      {
        label: "User",
        cell: (p) => `<span class="person-cell"><span class="avatar">${esc(initials(personName(p)))}</span><span><strong>${esc(personName(p))}</strong><small>${esc(p.place || shortId(p.user_id))}</small></span></span>`,
      },
      { label: "Last active", cell: (p) => timeTag(p.last_active_at) },
      { label: "Replies", align: "right", cell: (p) => `${num(p.replies)}${p.replies_7d ? `<small>${num(p.replies_7d)} this week</small>` : ""}` },
      { label: "Memories", align: "right", cell: (p) => `${p.memories ? num(p.memories) : '<span class="muted">0</span>'}${p.profile_facts ? `<small>${num(p.profile_facts)} profile facts</small>` : ""}` },
      { label: "Failed", align: "right", cell: (p) => (p.failed_replies ? `<span class="tone-bad">${num(p.failed_replies)}</span>` : '<span class="muted">0</span>') },
      { label: "Spend", align: "right", cell: (p) => usd(p.cost_usd) },
      { label: "Joined", cell: (p) => timeTag(p.joined_at), className: "hide-narrow" },
    ],
    rows,
    {
      emptyText: state.people.length ? "No users match." : "No users yet.",
      rowAttrs: (p) => `data-user-id="${esc(p.user_id)}" tabindex="0" class="clickable ${p.user_id === selectedId ? "selected" : ""}"`,
    },
  );
}

export function personView(person) {
  const profile = person.profile || {};
  const usage = person.usage || {};
  const memory = person.memory || {};
  const matching = person.matching || {};
  const settings = person.settings || {};
  const name = personName(person);
  const place = [profile.city, profile.region, profile.country].filter(Boolean).join(", ");

  return `
    <section class="panel person-head">
      <a class="text-link close-detail" href="/users" data-link aria-label="Close">✕</a>
      <div class="person-title">
        <span class="avatar large">${esc(initials(name))}</span>
        <div>
          <h2>${esc(name)}</h2>
          <p class="muted">${esc([place, profile.age ? `${profile.age} yrs` : ""].filter(Boolean).join(" · ") || "No profile details")}</p>
          <p class="id-line"><code>${esc(person.user_id)}</code> <button type="button" class="link-button" data-copy="${esc(person.user_id)}">Copy id</button></p>
        </div>
      </div>
      <div class="stats compact">
        ${stat({ label: "Replies", value: num(usage.replies), sub: `${num(usage.failed_replies)} failed` , tone: usage.failed_replies ? "warn" : "" })}
        ${stat({ label: "Memories", value: num(memory.active), sub: memory.last_updated_at ? `updated ${timeTag(memory.last_updated_at)}` : "none yet" })}
        ${stat({ label: "Spend", value: usd(usage.cost_usd), sub: `${num(usage.calls)} model calls` })}
        ${stat({ label: "Last reply", value: timeTag(usage.last_at), sub: `first ${timeTag(usage.first_at || profile.created_at)}` })}
      </div>
    </section>
    ${panel({ title: "Replies per day", kicker: "Last 30 days", body: barChart(usage.daily || [], [{ key: "replies", label: "Replies" }]) })}
    ${panel({
      title: "Chats",
      kicker: `${num(person.chats?.length)} total`,
      body: table(
        [
          { label: "Chat", cell: (c) => `${pill(c.channel)} ${c.kind !== "chat" ? pill(c.kind) : ""}${c.archived ? pill("archived") : ""}<small class="mono">${esc(shortId(c.id))}</small>` },
          { label: "Replies", align: "right", cell: (c) => num(c.replies) },
          { label: "Spend", align: "right", cell: (c) => usd(c.cost_usd) },
          { label: "Last message", cell: (c) => timeTag(c.updated_at) },
        ],
        person.chats || [],
        { emptyText: "No chats yet." },
      ),
    })}
    <div class="grid two">
      ${panel({
        title: "Memory",
        kicker: "Counts only",
        body: `${memory.by_kind?.length ? shareBars(memory.by_kind, { label: (row) => esc(titleize(row.kind)), value: (row) => row.active }) : '<p class="muted">No memories saved yet.</p>'}
          ${facts([
            ["Profile facts (older system)", num(memory.profile_facts)],
            ["Topics (threads)", num(memory.threads)],
            ["Open notes to follow up", num(memory.open_notes)],
            ["Open questions", num(memory.open_questions)],
            ["Chat uploads", num(memory.uploads)],
            ["Failing batches", memory.batch_failures ? `<span class="tone-bad">${num(memory.batch_failures)}</span>` : "0"],
          ])}`,
      })}
      ${panel({
        title: "Account",
        kicker: "Settings and links",
        body: facts([
          ["Joined", profile.created_at ? esc(when(profile.created_at)) : '<span class="muted">no profile</span>'],
          ["Adult confirmed", profile.adult_confirmed ? "Yes" : "No"],
          ["Photo", profile.has_photo ? "Yes" : "No"],
          ["Timezone", esc(settings.timezone || "-")],
          ["Omi messages first", settings.proactive_enabled == null ? "-" : settings.proactive_enabled ? "On" : "Off"],
          ["Reply model", esc(settings.reply_model || "default")],
          ["Linked", (person.channels || []).map((c) => pill(c.channel)).join(" ") || '<span class="muted">web only</span>'],
          ["Ratings", usage.feedback?.total ? `${num(usage.feedback.good)} good · ${num(usage.feedback.bad)} poor` : '<span class="muted">none</span>'],
        ]),
      })}
    </div>
    <div class="grid two">
      ${panel({
        title: "Matching",
        kicker: "Pools and pairs",
        body: facts([
          ["Vibe milestone", matching.milestone ? esc(titleize(matching.milestone)) : '<span class="muted">not started</span>'],
          ["Pools", (matching.pools || []).map((p) => `${esc(p.name)}${p.left_at ? " (left)" : ""}`).join(", ") || '<span class="muted">none</span>'],
          ["Pairs", num(matching.pairs)],
        ]),
      })}
      ${panel({
        title: "Who looked at this user",
        kicker: "Access log",
        body: table(
          [
            { label: "Action", cell: (a) => esc(titleize(a.action)) },
            { label: "By", cell: (a) => `${esc(a.actor_role || "")} <small class="mono">${esc(shortId(a.actor_id))}</small>` },
            { label: "When", cell: (a) => timeTag(a.created_at) },
          ],
          (person.audit || []).slice(0, 8),
          { emptyText: "No access recorded." },
        ),
      })}
    </div>`;
}
