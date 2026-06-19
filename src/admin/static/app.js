const state = {
  data: null,
  route: routeName()
};

const statusEl = document.querySelector("#admin-status");
const refreshButton = document.querySelector("#refresh-admin");

const metrics = {
  users: document.querySelector("#metric-users"),
  usersDetail: document.querySelector("#metric-users-detail"),
  conversations: document.querySelector("#metric-conversations"),
  conversationsDetail: document.querySelector("#metric-conversations-detail"),
  drafts: document.querySelector("#metric-drafts"),
  draftsDetail: document.querySelector("#metric-drafts-detail"),
  facts: document.querySelector("#metric-facts"),
  factsDetail: document.querySelector("#metric-facts-detail"),
  requests: document.querySelector("#metric-requests"),
  requestsDetail: document.querySelector("#metric-requests-detail"),
  tokens: document.querySelector("#metric-tokens"),
  tokensDetail: document.querySelector("#metric-tokens-detail"),
  cost: document.querySelector("#metric-cost")
};

const tables = {
  users: document.querySelector("#admin-users"),
  conversations: document.querySelector("#admin-conversations"),
  drafts: document.querySelector("#admin-drafts"),
  providerMix: document.querySelector("#admin-provider-mix"),
  usageEvents: document.querySelector("#admin-usage-events")
};

function routeName() {
  if (window.location.pathname === "/admin/users") return "users";
  if (window.location.pathname === "/admin/activity") return "activity";
  if (window.location.pathname === "/admin/usage") return "usage";
  return "dashboard";
}

function configureRoute() {
  document.querySelectorAll("[data-route]").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === state.route);
  });
  document.querySelectorAll("[data-section]").forEach((section) => {
    const visibleRoutes = String(section.dataset.section || "").split(" ");
    section.hidden = !visibleRoutes.includes(state.route);
  });

  const titles = {
    dashboard: ["Dashboard", "Live view of users, onboarding activity, and provider usage."],
    users: ["Users", "Track every user profile, onboarding session, and learned signal."],
    activity: ["Activity", "Review recent conversations and profile drafts."],
    usage: ["Usage", "Track Groq and agent API calls, tokens, failures, and cost."]
  };
  const [title, subtitle] = titles[state.route] || titles.dashboard;
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#page-subtitle").textContent = subtitle;
}

async function loadAdminOverview() {
  setStatus("Loading admin data...");
  try {
    const response = await fetch("/api/admin/overview?limit=50", {
      headers: { Accept: "application/json" }
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(data.detail, "Could not load admin data."));
    }
    state.data = data;
    renderDashboard(data);
    setStatus(`Updated ${new Date().toLocaleTimeString()}`);
  } catch (error) {
    setStatus(error.message);
    renderError(error.message);
  }
}

function renderDashboard(data) {
  renderMetrics(data.summary || {});
  renderUsers(data.users || []);
  renderConversations(data.recent_conversations || []);
  renderDrafts(data.recent_drafts || []);
  renderProviderMix(data.recent_usage_events || []);
  renderUsageEvents(data.recent_usage_events || []);
}

function renderMetrics(summary) {
  const usage = summary.usage || {};
  metrics.users.textContent = formatNumber(summary.user_count || 0);
  metrics.usersDetail.textContent = `${formatNumber(summary.anonymous_conversation_count || 0)} anonymous sessions`;
  metrics.conversations.textContent = formatNumber(summary.conversation_count || 0);
  metrics.conversationsDetail.textContent = `${formatNumber(summary.active_conversation_count || 0)} active / ${formatNumber(summary.extracted_conversation_count || 0)} extracted`;
  metrics.drafts.textContent = formatNumber(summary.draft_count || 0);
  metrics.draftsDetail.textContent = `${formatNumber(summary.approved_draft_count || 0)} approved`;
  metrics.facts.textContent = formatNumber(summary.learned_fact_count || 0);
  metrics.factsDetail.textContent = `${formatNumber(summary.context_source_count || 0)} context sources`;
  metrics.requests.textContent = formatNumber(usage.request_count || 0);
  metrics.requestsDetail.textContent = `${formatNumber(usage.failed_request_count || 0)} failures`;
  metrics.tokens.textContent = formatNumber(usage.total_tokens || 0);
  metrics.tokensDetail.textContent = `${formatNumber(usage.prompt_tokens || 0)} input / ${formatNumber(usage.completion_tokens || 0)} output`;
  metrics.cost.textContent = formatUsd(usage.estimated_cost_usd || 0);
}

function renderUsers(users) {
  if (!users.length) {
    tables.users.innerHTML = emptyRow(8, "No users have activity yet.");
    return;
  }
  tables.users.innerHTML = users.map((user) => `
    <tr>
      <td class="mono">${escapeHtml(shortId(user.user_id))}<small>${escapeHtml(user.display_name || user.user_id)}</small></td>
      <td>${escapeHtml(profileLabel(user))}</td>
      <td class="mono">${formatNumber(user.conversation_count || 0)}<small>${formatNumber(user.active_conversation_count || 0)} active</small></td>
      <td class="mono">${formatNumber(user.message_count || 0)}<small>${formatNumber(user.user_message_count || 0)} user</small></td>
      <td class="mono">${formatNumber(user.draft_count || 0)}<small>${formatNumber(user.approved_draft_count || 0)} approved</small></td>
      <td class="mono">${formatNumber(user.learned_fact_count || 0)}<small>${formatNumber(user.context_source_count || 0)} context</small></td>
      <td class="mono">${formatNumber(user.usage?.total_tokens || 0)}<small>${formatUsd(user.usage?.estimated_cost_usd || 0)}</small></td>
      <td>${formatDate(user.last_activity_at)}</td>
    </tr>
  `).join("");
}

function renderConversations(conversations) {
  if (!conversations.length) {
    tables.conversations.innerHTML = emptyRow(6, "No conversations yet.");
    return;
  }
  tables.conversations.innerHTML = conversations.map((conversation) => `
    <tr>
      <td class="mono">${escapeHtml(shortId(conversation.id))}<small>${escapeHtml(conversation.agent_model || conversation.agent_provider || "-")}</small></td>
      <td class="mono">${escapeHtml(shortId(conversation.user_id || "anonymous"))}</td>
      <td>${statusPill(conversation.status)}</td>
      <td class="mono">${formatNumber(conversation.message_count || 0)}<small>${formatNumber(conversation.user_message_count || 0)} user / ${formatNumber(conversation.context_source_count || 0)} context</small></td>
      <td class="mono">${formatNumber(conversation.usage?.total_tokens || 0)}<small>${formatNumber(conversation.usage?.request_count || 0)} calls</small></td>
      <td>${formatDate(conversation.updated_at)}</td>
    </tr>
  `).join("");
}

function renderDrafts(drafts) {
  if (!drafts.length) {
    tables.drafts.innerHTML = emptyRow(5, "No profile drafts yet.");
    return;
  }
  tables.drafts.innerHTML = drafts.map((draft) => `
    <tr>
      <td class="mono">${escapeHtml(shortId(draft.id))}<small>${escapeHtml(draft.display_name || draft.agent_provider || "-")}</small></td>
      <td class="mono">${escapeHtml(shortId(draft.user_id || "anonymous"))}</td>
      <td>${statusPill(draft.status)}</td>
      <td class="mono">${formatNumber(draft.warning_count || 0)}</td>
      <td>${formatDate(draft.updated_at)}</td>
    </tr>
  `).join("");
}

function renderProviderMix(events) {
  if (!events.length) {
    tables.providerMix.innerHTML = emptyRow(5, "No provider calls logged yet.");
    return;
  }
  const rows = Object.values(events.reduce((accumulator, event) => {
    const key = `${event.provider || "unknown"}:${event.model || "unknown"}`;
    if (!accumulator[key]) {
      accumulator[key] = {
        provider: event.provider || "unknown",
        model: event.model || "unknown",
        calls: 0,
        failures: 0,
        tokens: 0,
        cost: 0
      };
    }
    accumulator[key].calls += 1;
    accumulator[key].failures += event.success ? 0 : 1;
    accumulator[key].tokens += event.total_tokens || 0;
    accumulator[key].cost += event.estimated_cost_usd || 0;
    return accumulator;
  }, {})).sort((first, second) => second.tokens - first.tokens);

  tables.providerMix.innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.provider)}<small>${escapeHtml(row.model)}</small></td>
      <td class="mono">${formatNumber(row.calls)}</td>
      <td class="mono">${formatNumber(row.tokens)}</td>
      <td class="mono">${formatNumber(row.failures)}</td>
      <td class="mono">${formatUsd(row.cost)}</td>
    </tr>
  `).join("");
}

function renderUsageEvents(events) {
  if (!events.length) {
    tables.usageEvents.innerHTML = emptyRow(6, "No API usage events yet.");
    return;
  }
  tables.usageEvents.innerHTML = events.map((event) => `
    <tr>
      <td>${escapeHtml(usageKindLabel(event.request_kind))}<small>${formatDate(event.created_at)}</small></td>
      <td class="mono">${escapeHtml(shortId(event.user_id || "anonymous"))}</td>
      <td>${escapeHtml(event.provider || "-")}<small>${escapeHtml(event.model || "-")}</small></td>
      <td class="mono">${formatNumber(event.total_tokens || 0)}<small>${formatNumber(event.prompt_tokens || 0)} in / ${formatNumber(event.completion_tokens || 0)} out</small></td>
      <td class="mono">${formatNumber(event.latency_ms || 0)} ms</td>
      <td>${statusPill(event.success ? "success" : "failed")}</td>
    </tr>
  `).join("");
}

function renderError(message) {
  tables.users.innerHTML = emptyRow(8, message);
  tables.conversations.innerHTML = emptyRow(6, message);
  tables.drafts.innerHTML = emptyRow(5, message);
  tables.providerMix.innerHTML = emptyRow(5, message);
  tables.usageEvents.innerHTML = emptyRow(6, message);
}

function statusPill(value) {
  const text = value || "unknown";
  return `<span class="status-pill ${escapeHtml(text)}">${escapeHtml(titleize(text))}</span>`;
}

function profileLabel(user) {
  const gender = user.gender || "unknown";
  const interested = user.interested_in || "unknown";
  return `${titleize(gender)} -> ${titleize(interested)}`;
}

function usageKindLabel(kind) {
  const labels = {
    chat_reply: "Chat reply",
    input_guardrail: "Input guardrail",
    profile_extract: "Profile extraction",
    profile_extract_repair: "Extraction repair",
    profile_signal_extract: "Signal extraction",
    profile_signal_backfill: "Signal backfill",
    profile_fact_aggregate: "Fact aggregation",
    match_snapshot_generate: "Match snapshot"
  };
  return labels[kind] || titleize(String(kind || "API call").replaceAll("_", " "));
}

function apiErrorMessage(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || item.message || String(item)).join(", ");
  return fallback;
}

function setStatus(message) {
  statusEl.textContent = message;
}

function emptyRow(colspan, message) {
  return `<tr><td class="empty-row" colspan="${colspan}">${escapeHtml(message)}</td></tr>`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-IN").format(Number(value || 0));
}

function formatUsd(value) {
  return `$${Number(value || 0).toFixed(6)}`;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 12) return text;
  return text.slice(0, 8);
}

function titleize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

refreshButton.addEventListener("click", loadAdminOverview);
configureRoute();
loadAdminOverview();
