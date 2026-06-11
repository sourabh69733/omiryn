let messages = [];
let conversationId = null;
let activeDraftId = null;
let isSendingMessage = false;

const routes = {
  interview: document.querySelector("#interview-screen"),
  review: document.querySelector("#review-screen"),
  matches: document.querySelector("#matches-screen"),
  usage: document.querySelector("#usage-screen")
};

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const sendMessage = document.querySelector("#send-message");
const agentStatus = document.querySelector("#agent-status");
const resetChat = document.querySelector("#reset-chat");
const sidebarResetChat = document.querySelector("#sidebar-reset-chat");
const extractProfile = document.querySelector("#extract-profile");
const readinessScore = document.querySelector("#readiness-score");
const readinessMeter = document.querySelector("#readiness-meter");
const signalList = document.querySelector("#signal-list");
const usageSummary = document.querySelector("#usage-summary");
const sideTabButtons = document.querySelectorAll("[data-side-tab]");
const sidePanels = document.querySelectorAll("[data-side-panel]");
const sidebarMessageCount = document.querySelector("#sidebar-message-count");
const sidebarConversationId = document.querySelector("#sidebar-conversation-id");

const refreshMatches = document.querySelector("#refresh-matches");
const matchList = document.querySelector("#match-list");

const refreshUsage = document.querySelector("#refresh-usage");
const usageRequests = document.querySelector("#usage-requests");
const usageRequestDetail = document.querySelector("#usage-request-detail");
const usageTotalTokens = document.querySelector("#usage-total-tokens");
const usageTokenDetail = document.querySelector("#usage-token-detail");
const usageCost = document.querySelector("#usage-cost");
const usageCostDetail = document.querySelector("#usage-cost-detail");
const usageFailures = document.querySelector("#usage-failures");
const providerList = document.querySelector("#provider-list");
const usageEvents = document.querySelector("#usage-events");

const saveDraft = document.querySelector("#save-draft");
const approveDraft = document.querySelector("#approve-draft");
const deleteDraft = document.querySelector("#delete-draft");
const draftStatus = document.querySelector("#draft-status");
const warningList = document.querySelector("#warning-list");
const reviewNav = document.querySelector("#review-nav");
const draftInputs = {
  name: document.querySelector("#draft-name"),
  city: document.querySelector("#draft-city"),
  intent: document.querySelector("#draft-intent"),
  communication: document.querySelector("#draft-communication"),
  family: document.querySelector("#draft-family"),
  children: document.querySelector("#draft-children"),
  values: document.querySelector("#draft-values"),
  lifestyle: document.querySelector("#draft-lifestyle"),
  dealbreakers: document.querySelector("#draft-dealbreakers"),
  summary: document.querySelector("#draft-summary")
};

function showScreen(name) {
  Object.entries(routes).forEach(([key, element]) => {
    element.hidden = key !== name;
  });
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === name);
  });
}

function currentDraftIdFromPath() {
  const match = window.location.pathname.match(/^\/drafts\/([^/]+)$/);
  return match ? match[1] : null;
}

async function startConversation() {
  loadAgentStatus();
  chatInput.disabled = true;
  extractProfile.disabled = true;
  const response = await fetch("/api/agent/conversations", { method: "POST" });
  const conversation = await response.json();
  conversationId = conversation.id;
  messages = conversation.messages;
  chatInput.disabled = false;
  extractProfile.disabled = false;
  renderMessages();
  updateReadiness();
  updateSidebarMeta();
  loadAgentUsage();
  focusChatInput();
}

async function loadAgentStatus() {
  if (!agentStatus) return;

  try {
    const response = await fetch("/api/agent/status");
    const status = await response.json();
    const provider = titleCase(status.provider || "unknown");
    const model = status.model || "no model";
    agentStatus.textContent = `${provider} · ${model}`;
  } catch {
    agentStatus.textContent = "Agent status unavailable";
  }
}

function titleCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function renderMessages() {
  chatLog.innerHTML = "";
  messages.forEach((message, index) => {
    const bubble = document.createElement("div");
    bubble.className = `message ${message.role === "assistant" ? "agent" : "user"}`;

    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = message.content;
    bubble.appendChild(content);

    // Later: show extracted signal chips below assistant replies.

    chatLog.appendChild(bubble);
  });
  chatLog.scrollTop = chatLog.scrollHeight;
  updateSidebarMeta();
}

function updateSidebarMeta() {
  if (sidebarMessageCount) {
    const userMessages = messages.filter((message) => message.role === "user").length;
    const totalMessages = messages.length;
    sidebarMessageCount.textContent = `${totalMessages} messages · ${userMessages} user`;
  }

  if (sidebarConversationId) {
    sidebarConversationId.textContent = conversationId
      ? `Session ${conversationId.slice(0, 8)}`
      : "No conversation started.";
  }
}

function showSidePanel(name) {
  sideTabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.sideTab === name);
  });
  sidePanels.forEach((panel) => {
    panel.hidden = panel.dataset.sidePanel !== name;
    panel.classList.toggle("active", panel.dataset.sidePanel === name);
  });
}

function updateReadiness() {
  const userMessageCount = messages.filter((message) => message.role === "user").length;
  const score = Math.min(100, 20 + userMessageCount * 20);
  readinessScore.textContent = `${score}%`;
  readinessMeter.style.width = `${score}%`;

  Array.from(signalList.children).forEach((item, index) => {
    item.classList.toggle("complete", index < Math.max(1, userMessageCount + 1));
  });
}

async function sendUserMessage() {
  if (isSendingMessage) return;

  const text = chatInput.value.trim();
  if (!text || !conversationId) return;

  messages.push({ role: "user", content: text });
  chatInput.value = "";
  isSendingMessage = true;
  renderMessages();
  updateReadiness();
  focusChatInput();

  try {
    const response = await fetch(`/api/agent/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });
    const conversation = await response.json();

    if (!response.ok) {
      throw new Error(conversation.detail || "The agent could not reply.");
    }

    messages = conversation.messages || messages;
  } catch (error) {
    messages.push({
      role: "assistant",
      content: `I could not answer that yet. ${error.message}`
    });
  } finally {
    isSendingMessage = false;
    renderMessages();
    updateReadiness();
    loadAgentUsage();
    focusChatInput();
  }
}

async function loadAgentUsage() {
  if (!usageSummary || !conversationId) return;

  try {
    const response = await fetch(`/api/agent/conversations/${conversationId}/usage`);
    const data = await response.json();
    const summary = data.summary || {};
    const cost = summary.estimated_cost_usd
      ? ` · $${summary.estimated_cost_usd.toFixed(6)}`
      : "";
    const inrCost = summary.estimated_cost_inr
      ? ` / ₹${summary.estimated_cost_inr.toFixed(4)}`
      : "";
    usageSummary.textContent = [
      `${summary.request_count || 0} agent requests`,
      `${summary.total_tokens || 0} total tokens`,
      `${summary.prompt_tokens || 0} in / ${summary.completion_tokens || 0} out${cost}${inrCost}`
    ].join(" · ");
  } catch {
    usageSummary.textContent = "Usage unavailable";
  }
}

function focusChatInput() {
  window.requestAnimationFrame(() => {
    chatInput.focus();
  });
}

async function extractConversationDraft() {
  if (!conversationId) return;

  extractProfile.disabled = true;
  extractProfile.textContent = "Extracting...";
  await loadAgentUsage();
  const response = await fetch(`/api/agent/conversations/${conversationId}/extract`, {
    method: "POST"
  });
  const data = await response.json();
  extractProfile.disabled = false;
  extractProfile.textContent = "Extract review draft";
  await loadAgentUsage();

  if (data.review_url) {
    window.location.href = data.review_url;
  }
}

async function loadDraft(draftId) {
  const response = await fetch(`/api/drafts/${draftId}`);
  if (!response.ok) {
    setDraftStatus("Draft not found.", "deleted");
    setDraftButtons("deleted");
    return;
  }

  const draft = await response.json();
  activeDraftId = draft.id;
  reviewNav.href = `/drafts/${draft.id}`;
  fillDraftForm(draft);
  renderExtractionWarnings(draft.submission.extraction_warnings || []);
  setDraftStatus(
    draft.status === "approved"
      ? "Approved. This profile is ready for matching."
      : "Draft loaded. Review and edit before approving.",
    draft.status
  );
  setDraftButtons(draft.status);
}

function renderExtractionWarnings(warnings) {
  if (!warnings.length) {
    warningList.hidden = true;
    warningList.innerHTML = "";
    return;
  }

  warningList.hidden = false;
  warningList.innerHTML = warnings
    .map((warning) => `<span>${warning}</span>`)
    .join("");
}

function fillDraftForm(draft) {
  const submission = draft.submission;
  draftInputs.name.value = submission.display_name || "";
  draftInputs.city.value = submission.city.value;
  draftInputs.intent.value = submission.relationship_intent.value;
  draftInputs.communication.value = submission.communication_style.value;
  draftInputs.family.value = submission.family_expectations.value;
  draftInputs.children.value = submission.children_preference.value;
  draftInputs.values.value = submission.values.values.join(", ");
  draftInputs.lifestyle.value = submission.lifestyle.values.join(", ");
  draftInputs.dealbreakers.value = submission.dealbreakers.values.join(", ");
  draftInputs.summary.value = submission.summary || "";
}

function draftPatchFromForm() {
  return {
    display_name: draftInputs.name.value.trim(),
    city: draftInputs.city.value.trim(),
    relationship_intent: draftInputs.intent.value.trim(),
    communication_style: draftInputs.communication.value.trim(),
    family_expectations: draftInputs.family.value.trim(),
    children_preference: draftInputs.children.value.trim(),
    values: splitList(draftInputs.values.value),
    lifestyle: splitList(draftInputs.lifestyle.value),
    dealbreakers: splitList(draftInputs.dealbreakers.value),
    summary: draftInputs.summary.value.trim()
  };
}

function splitList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function setDraftStatus(text, status = "draft") {
  draftStatus.textContent = text;
  draftStatus.className = `draft-status ${status}`;
}

function setDraftButtons(status) {
  const editable = status === "draft";
  saveDraft.disabled = !editable;
  approveDraft.disabled = !editable;
  deleteDraft.disabled = !activeDraftId || status === "deleted";
}

async function saveDraftEdits() {
  if (!activeDraftId) return;
  const response = await fetch(`/api/drafts/${activeDraftId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draftPatchFromForm())
  });
  const draft = await response.json();
  fillDraftForm(draft);
  setDraftStatus("Saved. Approval is still required before matching.", "draft");
}

async function approveCurrentDraft() {
  if (!activeDraftId) return;
  await fetch(`/api/drafts/${activeDraftId}/approve`, { method: "POST" });
  await loadDraft(activeDraftId);
  window.location.href = "/matches";
}

async function deleteCurrentDraft() {
  if (!activeDraftId) return;
  await fetch(`/api/drafts/${activeDraftId}`, { method: "DELETE" });
  activeDraftId = null;
  setDraftStatus("Deleted. This draft will not enter matching.", "deleted");
  setDraftButtons("deleted");
}

async function loadMatches() {
  matchList.innerHTML = '<div class="loading-row">Loading suggestions...</div>';
  const response = await fetch("/api/demo/matches");
  const data = await response.json();

  matchList.innerHTML = "";
  data.matches.forEach((match) => {
    const item = document.createElement("article");
    item.className = `match-item ${match.result.decision === "reject" ? "rejected" : ""}`;
    const breakdown = Object.entries(match.result.breakdown)
      .map(([key, value]) => `<span>${key}: ${value}</span>`)
      .join("");

    item.innerHTML = `
      <div class="match-top">
        <div>
          <h2>${match.name}</h2>
          <p>${match.age} · ${match.city || "Location open"}</p>
        </div>
        <strong>${match.result.score}</strong>
      </div>
      <p class="match-copy">${match.result.explanation}</p>
      <div class="breakdown">${breakdown}</div>
      <div class="match-actions">
        <button type="button">Accept</button>
        <button class="secondary-button" type="button">Pass</button>
      </div>
    `;
    matchList.appendChild(item);
  });
}

async function loadUsageDashboard() {
  if (!usageEvents) return;

  usageEvents.innerHTML = '<tr><td colspan="6">Loading usage...</td></tr>';
  providerList.innerHTML = '<div class="loading-row">Loading provider mix...</div>';

  try {
    const response = await fetch("/api/agent/usage");
    const data = await response.json();
    renderUsageSummary(data.summary || {});
    renderProviderMix(data.events || []);
    renderUsageEvents(data.events || []);
  } catch (error) {
    usageEvents.innerHTML = `<tr><td colspan="6">Could not load usage. ${escapeHtml(error.message)}</td></tr>`;
    providerList.innerHTML = '<div class="loading-row">Usage unavailable.</div>';
  }
}

function renderUsageSummary(summary) {
  usageRequests.textContent = formatNumber(summary.request_count || 0);
  usageRequestDetail.textContent = `${formatNumber(summary.successful_request_count || 0)} successful`;
  usageTotalTokens.textContent = formatNumber(summary.total_tokens || 0);
  usageTokenDetail.textContent = `${formatNumber(summary.prompt_tokens || 0)} input / ${formatNumber(summary.completion_tokens || 0)} output`;
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

function renderUsageEvents(events) {
  if (!events.length) {
    usageEvents.innerHTML = '<tr><td class="table-empty" colspan="6">No agent calls logged yet.</td></tr>';
    return;
  }

  usageEvents.innerHTML = events
    .slice(0, 40)
    .map((event) => {
      const statusClass = event.success ? "success" : "failed";
      const statusText = event.success ? "Success" : "Failed";
      const cost = event.estimated_cost_usd ? formatUsd(event.estimated_cost_usd) : "-";
      const createdAt = event.created_at ? new Date(event.created_at).toLocaleString() : "";
      return `
        <tr>
          <td>${escapeHtml(event.request_kind || "-")}<small>${escapeHtml(createdAt)}</small></td>
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

function formatNumber(value) {
  return new Intl.NumberFormat("en-IN").format(value);
}

function formatUsd(value) {
  return `$${Number(value).toFixed(6)}`;
}

function formatInr(value) {
  return `₹${Number(value).toFixed(4)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  event.stopPropagation();
  sendUserMessage();
});
chatInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;

  event.preventDefault();
  event.stopPropagation();
  sendUserMessage();
});
sendMessage.addEventListener("click", () => {
  sendUserMessage();
  focusChatInput();
});
resetChat.addEventListener("click", startConversation);
sidebarResetChat.addEventListener("click", startConversation);
extractProfile.addEventListener("click", extractConversationDraft);
saveDraft.addEventListener("click", saveDraftEdits);
approveDraft.addEventListener("click", approveCurrentDraft);
deleteDraft.addEventListener("click", deleteCurrentDraft);
refreshMatches.addEventListener("click", loadMatches);
refreshUsage.addEventListener("click", loadUsageDashboard);
sideTabButtons.forEach((button) => {
  button.addEventListener("click", () => showSidePanel(button.dataset.sideTab));
});

const draftId = currentDraftIdFromPath();
if (draftId) {
  showScreen("review");
  loadDraft(draftId);
} else if (window.location.pathname === "/matches") {
  showScreen("matches");
  loadMatches();
} else if (window.location.pathname === "/usage") {
  showScreen("usage");
  loadUsageDashboard();
} else {
  showScreen("interview");
  startConversation();
}
