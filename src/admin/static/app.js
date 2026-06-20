const state = {
  data: null,
  route: routeName(),
  usersPage: 1,
  usersPerPage: 10,
  selectedUserId: null,
  selectedUserDetail: null,
  visibleFactCount: 6
};

const statusEl = document.querySelector("#admin-status");
const refreshButton = document.querySelector("#refresh-admin");
const metricGrid = document.querySelector("#metric-grid");
const dashboardFunnel = document.querySelector("#dashboard-funnel");
const dashboardAttention = document.querySelector("#dashboard-attention");
const usersPageStatus = document.querySelector("#users-page-status");
const usersPrev = document.querySelector("#users-prev");
const usersNext = document.querySelector("#users-next");
const userDetailLayout = document.querySelector("#user-detail-layout");
const selectedUserTitle = document.querySelector("#selected-user-title");
const userReport = document.querySelector("#user-report");
const usageRequests = document.querySelector("#usage-requests");
const usageRequestDetail = document.querySelector("#usage-request-detail");
const usageTotalTokens = document.querySelector("#usage-total-tokens");
const usageTokenDetail = document.querySelector("#usage-token-detail");
const usageAverageInputTokens = document.querySelector("#usage-average-input-tokens");
const usageAverageOutputTokens = document.querySelector("#usage-average-output-tokens");
const usageCost = document.querySelector("#usage-cost");
const usageCostDetail = document.querySelector("#usage-cost-detail");
const usageFailures = document.querySelector("#usage-failures");
const usageRateLimits = document.querySelector("#usage-rate-limits");
const usageRateLimitDetail = document.querySelector("#usage-rate-limit-detail");
const providerList = document.querySelector("#provider-list");
const rateLimitGrid = document.querySelector("#rate-limit-grid");
const usageMinuteBuckets = document.querySelector("#usage-minute-buckets");
const usageEvents = document.querySelector("#usage-events");
const usageTableRowLimit = 20;

const metrics = {
  users: document.querySelector("#metric-users"),
  usersDetail: document.querySelector("#metric-users-detail"),
  activeUsers: document.querySelector("#metric-active-users"),
  onboardingStarted: document.querySelector("#metric-onboarding-started"),
  onboardingCompleted: document.querySelector("#metric-onboarding-completed"),
  approvedProfiles: document.querySelector("#metric-approved-profiles"),
  missingBasics: document.querySelector("#metric-missing-basics"),
  newUsers: document.querySelector("#metric-new-users"),
  newUsersDetail: document.querySelector("#metric-new-users-detail"),
  inactiveUsers: document.querySelector("#metric-inactive-users"),
  openDrafts: document.querySelector("#metric-open-drafts"),
  agentFailures: document.querySelector("#metric-agent-failures")
};

const tables = {
  users: document.querySelector("#admin-users")
};

function routeName() {
  if (window.location.pathname === "/admin/users") return "users";
  if (window.location.pathname === "/admin/usage") return "usage";
  return "dashboard";
}

function configureRoute() {
  document.querySelectorAll("[data-route]").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === state.route);
  });
  if (metricGrid) {
    metricGrid.hidden = state.route !== "dashboard";
  }
  document.querySelectorAll("[data-section]").forEach((section) => {
    const visibleRoutes = String(section.dataset.section || "").split(" ");
    section.hidden = !visibleRoutes.includes(state.route);
  });

  const titles = {
    dashboard: ["Dashboard", "Live view of users and product health."],
    users: ["Users", "Track every user profile, onboarding session, and learned signal."],
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
    if (state.route === "usage") {
      await loadUsageDashboard();
    }
    setStatus(`Updated ${new Date().toLocaleTimeString()}`);
  } catch (error) {
    setStatus(error.message);
    renderError(error.message);
  }
}

function renderDashboard(data) {
  renderMetrics(data.summary || {});
  renderDashboardInsights(data.summary || {});
  renderUsers(data.users || []);
  renderUsageDashboard(data.summary?.usage || {}, data.recent_usage_events || [], data.limits || {});
}

function renderMetrics(summary) {
  setText(metrics.users, formatNumber(summary.user_count || 0));
  setText(metrics.usersDetail, "Registered user records");
  setText(metrics.activeUsers, formatNumber(summary.active_user_7d_count || 0));
  setText(metrics.onboardingStarted, formatNumber(summary.onboarding_started_user_count || 0));
  setText(metrics.onboardingCompleted, formatNumber(summary.onboarding_completed_user_count || 0));
  setText(metrics.approvedProfiles, formatNumber(summary.approved_profile_user_count || 0));
  setText(metrics.missingBasics, formatNumber(summary.missing_profile_basics_user_count || 0));
  setText(metrics.newUsers, formatNumber(summary.new_user_7d_count || 0));
  setText(metrics.newUsersDetail, `${formatNumber(summary.new_user_today_count || 0)} today`);
  setText(metrics.inactiveUsers, formatNumber(summary.inactive_user_count || 0));
  setText(metrics.openDrafts, formatNumber(summary.open_draft_count || 0));
  setText(metrics.agentFailures, formatNumber(summary.agent_failure_today_count || 0));
}

function renderDashboardInsights(summary) {
  renderFunnel(summary);
  renderAttention(summary);
}

function renderFunnel(summary) {
  if (!dashboardFunnel) return;
  const totalUsers = summary.user_count || 0;
  const items = [
    ["Total users", totalUsers],
    ["Onboarding started", summary.onboarding_started_user_count || 0],
    ["Onboarding completed", summary.onboarding_completed_user_count || 0],
    ["Approved profiles", summary.approved_profile_user_count || 0],
  ];
  dashboardFunnel.innerHTML = items.map(([label, value]) => {
    const percent = totalUsers ? Math.round((value / totalUsers) * 100) : 0;
    return `
      <article class="funnel-row">
        <div>
          <strong>${escapeHtml(label)}</strong>
          <span>${formatNumber(value)} · ${formatNumber(percent)}%</span>
        </div>
        <div class="funnel-bar" aria-hidden="true">
          <i style="width: ${percent}%"></i>
        </div>
      </article>
    `;
  }).join("");
}

function renderAttention(summary) {
  if (!dashboardAttention) return;
  const items = [
    ["Pending profile approval", summary.open_draft_count || 0, "Drafts created but not approved"],
    ["Missing profile basics", summary.missing_profile_basics_user_count || 0, "Name, gender, or interest missing"],
    ["No recent activity", summary.inactive_user_count || 0, "Users inactive after starting"],
    ["Agent failures today", summary.agent_failure_today_count || 0, "Provider or runtime failures"],
  ];
  dashboardAttention.innerHTML = items.map(([label, value, detail]) => `
    <article class="attention-item ${value ? "warning" : "ok"}">
      <div>
        <strong>${escapeHtml(label)}</strong>
        <span>${escapeHtml(detail)}</span>
      </div>
      <b>${formatNumber(value)}</b>
    </article>
  `).join("");
}

function renderUsers(users) {
  if (!users.length) {
    tables.users.innerHTML = emptyRow(9, "No users have activity yet.");
    updateUsersPagination(0);
    return;
  }
  const pageCount = Math.max(1, Math.ceil(users.length / state.usersPerPage));
  state.usersPage = Math.min(Math.max(1, state.usersPage), pageCount);
  const start = (state.usersPage - 1) * state.usersPerPage;
  const pageUsers = users.slice(start, start + state.usersPerPage);
  tables.users.innerHTML = pageUsers.map((user) => `
    <tr class="selectable-row ${user.user_id === state.selectedUserId ? "selected" : ""}" data-user-id="${escapeHtml(user.user_id)}" tabindex="0">
      <td>${escapeHtml(user.display_name || "-")}<small>${escapeHtml(user.display_name_source || "unknown")}</small></td>
      <td class="mono">${escapeHtml(user.user_id)}</td>
      <td>${escapeHtml(profileLabel(user))}</td>
      <td class="mono">${formatNumber(user.conversation_count || 0)}<small>${formatNumber(user.active_conversation_count || 0)} active</small></td>
      <td class="mono">${formatNumber(user.message_count || 0)}<small>${formatNumber(user.user_message_count || 0)} user</small></td>
      <td class="mono">${formatNumber(user.draft_count || 0)}<small>${formatNumber(user.approved_draft_count || 0)} approved</small></td>
      <td class="mono">${formatNumber(user.learned_fact_count || 0)}<small>${formatNumber(user.context_source_count || 0)} context</small></td>
      <td class="mono">${formatNumber(user.usage?.total_tokens || 0)}<small>${formatUsd(user.usage?.estimated_cost_usd || 0)}</small></td>
      <td>${formatDate(user.last_activity_at)}</td>
    </tr>
  `).join("");
  updateUsersPagination(users.length);
}

function updateUsersPagination(totalUsers) {
  const pageCount = Math.max(1, Math.ceil(totalUsers / state.usersPerPage));
  usersPageStatus.textContent = `${formatNumber(totalUsers)} users · page ${formatNumber(state.usersPage)} of ${formatNumber(pageCount)}`;
  usersPrev.disabled = state.usersPage <= 1;
  usersNext.disabled = state.usersPage >= pageCount;
}

async function selectUser(userId) {
  if (!userId) return;
  state.selectedUserId = userId;
  state.visibleFactCount = 6;
  renderUsers(state.data?.users || []);
  selectedUserTitle.textContent = "Loading user report...";
  userReport.innerHTML = '<div class="table-empty">Loading selected user...</div>';

  try {
    const response = await fetch(`/api/admin/users/${encodeURIComponent(userId)}?limit=100`, {
      headers: { Accept: "application/json" }
    });
    const detail = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(detail.detail, "Could not load selected user."));
    }
    state.selectedUserDetail = detail;
    renderUserReport(detail);
    setStatus(`Selected ${detail.user.display_name || detail.user.user_id}`);
  } catch (error) {
    userReport.innerHTML = `<div class="table-empty">${escapeHtml(error.message)}</div>`;
    setStatus(error.message);
  }
}

function renderUserReport(detail) {
  const user = detail.user || {};
  const profile = detail.profile || {};
  const conversations = detail.conversations || [];
  const facts = detail.facts || [];
  selectedUserTitle.textContent = user.display_name || "Unnamed user";
  const profileSource = profile.source ? titleize(profile.source) : "Profile";
  userReport.innerHTML = `
    <div class="report-grid">
      ${reportCard("Name", user.display_name || "-", user.display_name_source ? `Source: ${user.display_name_source}` : "")}
      ${reportCard("Gender", profile.gender || "-", profileSource)}
      ${reportCard("Interested in", profile.interested_in || "-", profileSource)}
      ${reportCard("Conversations", formatNumber(user.conversation_count || 0), `${formatNumber(user.message_count || 0)} total messages`)}
      ${reportCard("Usage", formatNumber(user.usage?.total_tokens || 0), `${formatNumber(user.usage?.request_count || 0)} API calls`)}
      ${reportCard("Last activity", formatDate(user.last_activity_at), user.user_id || "")}
    </div>
    ${renderFactsSection(facts)}
    ${renderConversationSection(conversations)}
  `;
  document.querySelector("#show-more-facts")?.addEventListener("click", () => {
    state.visibleFactCount += 6;
    renderUserReport(state.selectedUserDetail);
  });
}

function reportCard(label, value, detail = "") {
  return `
    <article class="report-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
    </article>
  `;
}

function renderFactsSection(facts) {
  const visibleFacts = facts.slice(0, state.visibleFactCount);
  return `
    <section class="detail-section">
      <div class="detail-section-header">
        <h3>Profile facts</h3>
        <span class="mono">${formatNumber(facts.length)} facts</span>
      </div>
      ${
        visibleFacts.length
          ? `<div class="fact-list">${visibleFacts.map(renderFactItem).join("")}</div>`
          : '<div class="table-empty">No learned facts yet.</div>'
      }
      ${
        facts.length > visibleFacts.length
          ? `<div class="table-empty"><button class="secondary-button" id="show-more-facts" type="button">Show more facts</button></div>`
          : ""
      }
    </section>
  `;
}

function renderFactItem(fact) {
  return `
    <article class="fact-item">
      <strong>${escapeHtml(fact.label || fact.key || "Fact")}</strong>
      <small>${escapeHtml(fact.category || "other")} · confidence ${formatNumber(Math.round((fact.confidence || 0) * 100))}% · ${escapeHtml(fact.status || "-")}</small>
    </article>
  `;
}

function renderConversationSection(conversations) {
  return `
    <section class="detail-section">
      <div class="detail-section-header">
        <h3>Chat conversations</h3>
        <span class="mono">${formatNumber(conversations.length)} conversations</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Conversation</th>
              <th>Status</th>
              <th>Messages</th>
              <th>Tokens</th>
              <th>API calls</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            ${
              conversations.length
                ? conversations.map(renderConversationReportRow).join("")
                : '<tr><td class="table-empty" colspan="6">No conversations yet.</td></tr>'
            }
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderConversationReportRow(conversation) {
  return `
    <tr>
      <td class="mono">${escapeHtml(conversation.id)}<small>${escapeHtml(conversation.agent_model || conversation.agent_provider || "-")}</small></td>
      <td>${statusPill(conversation.status)}</td>
      <td class="mono">${formatNumber(conversation.message_count || 0)}<small>${formatNumber(conversation.user_message_count || 0)} user / ${formatNumber(conversation.context_source_count || 0)} context</small></td>
      <td class="mono">${formatNumber(conversation.usage?.total_tokens || 0)}<small>${formatNumber(conversation.usage?.prompt_tokens || 0)} in / ${formatNumber(conversation.usage?.completion_tokens || 0)} out</small></td>
      <td class="mono">${formatNumber(conversation.usage?.request_count || 0)}<small>${formatNumber(conversation.usage?.failed_request_count || 0)} failed</small></td>
      <td>${formatDate(conversation.updated_at)}</td>
    </tr>
  `;
}

async function loadUsageDashboard() {
  if (!usageEvents) return;

  usageEvents.innerHTML = '<tr><td colspan="6">Loading usage...</td></tr>';
  providerList.innerHTML = '<div class="table-empty">Loading provider mix...</div>';
  if (usageMinuteBuckets) {
    usageMinuteBuckets.innerHTML = '<tr><td colspan="4">Loading usage...</td></tr>';
  }

  try {
    const response = await fetch("/api/admin/usage?limit=100", {
      headers: { Accept: "application/json" }
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(data.detail, "Could not load usage."));
    }
    renderUsageDashboard(data.summary || {}, data.events || [], data.limits || {});
  } catch (error) {
    usageEvents.innerHTML = `<tr><td colspan="6">Could not load usage. ${escapeHtml(error.message)}</td></tr>`;
    providerList.innerHTML = '<div class="table-empty">Usage unavailable.</div>';
    if (rateLimitGrid) {
      rateLimitGrid.innerHTML = '<div class="table-empty">Rate-limit data unavailable.</div>';
    }
    if (usageMinuteBuckets) {
      usageMinuteBuckets.innerHTML = '<tr><td colspan="4">Usage unavailable.</td></tr>';
    }
  }
}

function renderUsageDashboard(summary, events = [], limits = {}) {
  renderUsageSummary(summary, events);
  renderProviderMix(events);
  renderGroqRateLimitHealth(events, limits);
  renderTokensByMinute(events);
  renderUsageEvents(events);
}

function renderGroqRateLimitHealth(events, limits = {}) {
  if (!rateLimitGrid) return;

  const groqEvents = events.filter((event) => event.provider === "groq");
  const rateLimitedEvents = groqEvents.filter((event) => isRateLimitEvent(event));
  const localDaily = localGroqDaily(groqEvents);
  const todayRateLimitedEvents = localDaily.events.filter((event) => isRateLimitEvent(event));
  if (usageRateLimits) {
    usageRateLimits.textContent = formatNumber(todayRateLimitedEvents.length);
  }
  if (usageRateLimitDetail) {
    usageRateLimitDetail.textContent = todayRateLimitedEvents.length
      ? `${formatNumber(todayRateLimitedEvents.length)} today · ${formatNumber(rateLimitedEvents.length)} logged`
      : "No recent throttling";
  }

  const localRate = localGroqRate(groqEvents);
  rateLimitGrid.innerHTML = `
    ${usageLimitMetric("RPM", localRate.rpmValue, limits.groq_rpm, "Requests consumed in last 60 seconds")}
    ${usageLimitMetric("RPD", localDaily.requests, limits.groq_rpd, "Requests consumed today")}
    ${usageLimitMetric("TPM", localRate.tpm, limits.groq_tpm, "Tokens consumed in last 60 seconds")}
    ${usageLimitMetric("TPD", localDaily.tokens, limits.groq_tpd, `${formatNumber(localDaily.promptTokens)} input / ${formatNumber(localDaily.completionTokens)} output today`)}
    ${rateLimitMetric("Total requests", formatNumber(groqEvents.length), "All logged Groq requests")}
    ${rateLimitMetric("Total tokens", formatNumber(totalGroqTokens(groqEvents)), "All logged Groq input + output tokens")}
    ${rateLimitMetric("429 today", formatNumber(todayRateLimitedEvents.length), `${formatNumber(rateLimitedEvents.length)} total 429 responses logged`)}
  `;
}

function usageLimitMetric(label, used, limit, fallbackDetail) {
  if (!limit) {
    return rateLimitMetric(label, formatNumber(used), `${fallbackDetail} · set ${usageLimitEnvName(label)} to show remaining`);
  }

  const remaining = Math.max(0, limit - used);
  const percent = Math.min(100, Math.round((used / limit) * 100));
  const state = percent >= 90 ? "danger" : percent >= 75 ? "warning" : "ok";
  return `
    <article class="rate-limit-card ${state}">
      <span>${label}</span>
      <strong>${formatNumber(used)} / ${formatNumber(limit)}</strong>
      <small>${formatNumber(remaining)} remaining · ${percent}% used</small>
    </article>
  `;
}

function rateLimitMetric(label, value, detail) {
  return `
    <article class="rate-limit-card">
      <span>${label}</span>
      <strong>${value}</strong>
      <small>${detail}</small>
    </article>
  `;
}

function usageLimitEnvName(label) {
  const envNames = {
    RPM: "GROQ_RPM_LIMIT",
    RPD: "GROQ_RPD_LIMIT",
    TPM: "GROQ_TPM_LIMIT",
    TPD: "GROQ_TPD_LIMIT"
  };
  return envNames[label] || "GROQ_*_LIMIT";
}

function isRateLimitEvent(event) {
  const error = `${event.error || ""} ${JSON.stringify(event.raw_usage?.error || {})}`;
  return error.includes("429") || error.toLowerCase().includes("too many requests");
}

function localGroqRate(events) {
  const now = Date.now();
  const windowStart = now - 60_000;
  const windowEvents = events.filter((event) => {
    if (!event.created_at) return false;
    const createdAt = new Date(event.created_at);
    if (Number.isNaN(createdAt.getTime())) return false;
    const timestamp = createdAt.getTime();
    return timestamp >= windowStart && timestamp <= now + 5_000;
  });
  const tokens = windowEvents.reduce((total, event) => total + (event.total_tokens || 0), 0);
  return {
    rpm: formatNumber(windowEvents.length),
    rpmValue: windowEvents.length,
    tpm: tokens
  };
}

function localGroqDaily(events) {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const todayEvents = events.filter((event) => {
    if (!event.created_at) return false;
    const createdAt = new Date(event.created_at);
    return !Number.isNaN(createdAt.getTime()) && createdAt >= startOfToday;
  });

  return {
    events: todayEvents,
    requests: todayEvents.length,
    promptTokens: todayEvents.reduce((total, event) => total + (event.prompt_tokens || 0), 0),
    completionTokens: todayEvents.reduce((total, event) => total + (event.completion_tokens || 0), 0),
    tokens: todayEvents.reduce((total, event) => total + (event.total_tokens || 0), 0)
  };
}

function totalGroqTokens(events) {
  return events.reduce((total, event) => total + (event.total_tokens || 0), 0);
}

function renderUsageSummary(summary, events = []) {
  const averageUsage = averageChatUsage(events, summary);
  usageRequests.textContent = formatNumber(summary.request_count || 0);
  usageRequestDetail.textContent = `${formatNumber(summary.successful_request_count || 0)} successful`;
  usageTotalTokens.textContent = formatNumber(summary.total_tokens || 0);
  usageTokenDetail.textContent = `${formatNumber(summary.prompt_tokens || 0)} input / ${formatNumber(summary.completion_tokens || 0)} output`;
  usageAverageInputTokens.textContent = formatNumber(averageUsage.prompt);
  usageAverageOutputTokens.textContent = formatNumber(averageUsage.completion);
  usageFailures.textContent = formatNumber(summary.failed_request_count || 0);

  if (summary.estimated_cost_usd) {
    usageCost.textContent = formatUsd(summary.estimated_cost_usd);
    usageCostDetail.textContent = summary.estimated_cost_inr
      ? `${formatInr(summary.estimated_cost_inr)} estimated`
      : "USD estimate";
  } else {
    usageCost.textContent = "$0.000000";
    usageCostDetail.textContent = "Set pricing env for estimates";
  }
}

function averageChatUsage(events, summary = {}) {
  if (summary.average_tokens_per_message || summary.average_prompt_tokens_per_message || summary.average_completion_tokens_per_message) {
    return {
      total: summary.average_tokens_per_message || 0,
      prompt: summary.average_prompt_tokens_per_message || 0,
      completion: summary.average_completion_tokens_per_message || 0
    };
  }

  const chatEvents = events.filter((event) =>
    event.success && event.request_kind === "chat_reply" && event.total_tokens
  );
  if (!chatEvents.length) {
    return { total: 0, prompt: 0, completion: 0 };
  }

  return {
    total: Math.round(chatEvents.reduce((total, event) => total + (event.total_tokens || 0), 0) / chatEvents.length),
    prompt: Math.round(chatEvents.reduce((total, event) => total + (event.prompt_tokens || 0), 0) / chatEvents.length),
    completion: Math.round(chatEvents.reduce((total, event) => total + (event.completion_tokens || 0), 0) / chatEvents.length)
  };
}

function renderProviderMix(events) {
  if (!events.length) {
    providerList.innerHTML = '<div class="table-empty">No agent usage yet.</div>';
    return;
  }

  const totals = events.reduce((accumulator, event) => {
    const key = `${event.provider || "unknown"} · ${event.model || "unknown"}`;
    if (!accumulator[key]) {
      accumulator[key] = {
        provider: event.provider || "unknown",
        model: event.model || "unknown",
        requests: 0,
        tokens: 0,
        cost: 0
      };
    }
    accumulator[key].requests += 1;
    accumulator[key].tokens += event.total_tokens || 0;
    accumulator[key].cost += event.estimated_cost_usd || 0;
    return accumulator;
  }, {});
  const rows = Object.values(totals).sort((first, second) => second.tokens - first.tokens);

  providerList.innerHTML = `
    <table class="provider-table">
      <thead>
        <tr>
          <th>Provider</th>
          <th>Calls</th>
          <th>Tokens</th>
          <th>Cost</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row) => `
              <tr>
                <td>${escapeHtml(row.provider)}<small>${escapeHtml(row.model)}</small></td>
                <td class="mono">${formatNumber(row.requests)}</td>
                <td class="mono">${formatNumber(row.tokens)}</td>
                <td class="mono">${row.cost ? formatUsd(row.cost) : "-"}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderTokensByMinute(events) {
  if (!usageMinuteBuckets) return;

  const buckets = events.reduce((accumulator, event) => {
    if (!event.created_at) return accumulator;
    const createdAt = new Date(event.created_at);
    if (Number.isNaN(createdAt.getTime())) return accumulator;

    createdAt.setSeconds(0, 0);
    const key = createdAt.getTime();
    if (!accumulator[key]) {
      accumulator[key] = {
        minute: createdAt,
        calls: 0,
        promptTokens: 0,
        completionTokens: 0,
        totalTokens: 0
      };
    }

    accumulator[key].calls += 1;
    accumulator[key].promptTokens += event.prompt_tokens || 0;
    accumulator[key].completionTokens += event.completion_tokens || 0;
    accumulator[key].totalTokens += event.total_tokens || 0;
    return accumulator;
  }, {});

  const rows = Object.values(buckets).sort((first, second) => second.minute - first.minute);
  if (!rows.length) {
    usageMinuteBuckets.innerHTML = '<tr><td class="table-empty" colspan="4">No token minutes yet.</td></tr>';
    return;
  }

  usageMinuteBuckets.innerHTML = rows
    .slice(0, usageTableRowLimit)
    .map((row) => `
      <tr>
        <td>${formatMinute(row.minute)}</td>
        <td class="mono">${formatNumber(row.calls)}</td>
        <td class="mono">${formatNumber(row.totalTokens)}</td>
        <td class="mono">${formatNumber(row.promptTokens)} in / ${formatNumber(row.completionTokens)} out</td>
      </tr>
    `)
    .join("");
}

function renderUsageEvents(events) {
  if (!events.length) {
    usageEvents.innerHTML = '<tr><td class="table-empty" colspan="6">No agent calls logged yet.</td></tr>';
    return;
  }

  usageEvents.innerHTML = events
    .slice(0, usageTableRowLimit)
    .map((event) => {
      const statusClass = event.success ? "success" : "failed";
      const statusText = event.success ? "Success" : "Failed";
      const cost = event.estimated_cost_usd ? formatUsd(event.estimated_cost_usd) : "-";
      const createdAt = event.created_at ? new Date(event.created_at).toLocaleString() : "";
      return `
        <tr>
          <td>${escapeHtml(usageKindLabel(event.request_kind))}<small>${escapeHtml(createdAt)}</small></td>
          <td>${escapeHtml(event.provider || "-")}<small>${escapeHtml(event.model || "-")}</small></td>
          <td class="mono">${formatNumber(event.total_tokens || 0)}<small>${formatNumber(event.prompt_tokens || 0)} in / ${formatNumber(event.completion_tokens || 0)} out</small></td>
          <td class="mono">${formatNumber(event.latency_ms || 0)} ms</td>
          <td class="mono">${cost}</td>
          <td><span class="status-pill ${statusClass}">${statusText}</span></td>
        </tr>
      `;
    })
    .join("");
}

function renderError(message) {
  tables.users.innerHTML = emptyRow(8, message);
  if (providerList) {
    providerList.innerHTML = `<div class="table-empty">${escapeHtml(message)}</div>`;
  }
  if (usageEvents) {
    usageEvents.innerHTML = emptyRow(6, message);
  }
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

function setText(element, value) {
  if (!element) return;
  element.textContent = value;
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

function formatInr(value) {
  return `₹${Number(value || 0).toFixed(4)}`;
}

function formatMinute(value) {
  return value.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
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
usersPrev?.addEventListener("click", () => {
  state.usersPage -= 1;
  renderUsers(state.data?.users || []);
});
usersNext?.addEventListener("click", () => {
  state.usersPage += 1;
  renderUsers(state.data?.users || []);
});
tables.users?.addEventListener("click", (event) => {
  const row = event.target.closest("[data-user-id]");
  if (!row) return;
  selectUser(row.dataset.userId);
});
tables.users?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("[data-user-id]");
  if (!row) return;
  event.preventDefault();
  selectUser(row.dataset.userId);
});
configureRoute();
loadAdminOverview();
