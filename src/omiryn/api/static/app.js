const starterMessages = [
  {
    role: "agent",
    text:
      "Hi, I am Omiryn's matchmaker. Are you looking for something serious, marriage-oriented, exploring, or something else?"
  },
  {
    role: "user",
    text: "I want a long-term relationship with someone emotionally steady and family-oriented."
  },
  {
    role: "agent",
    text: "What kind of communication makes you feel respected when things are tense?"
  }
];

const agentReplies = [
  "That helps. What would be a hard no for you in a relationship?",
  "Got it. How involved should family be once things become serious?",
  "Thanks. What kind of lifestyle rhythm fits you best during a normal week?",
  "Clear. I will keep that as a preference signal, not a public profile line."
];

const extractedProfiles = [
  {
    intent: "Long-term",
    city: "Bengaluru",
    communication: "Direct",
    family: "Medium involvement",
    values: ["family", "ambition", "emotional stability"],
    dealbreakers: ["smoking", "unclear intent"],
    confidence: 72
  },
  {
    intent: "Marriage-oriented",
    city: "Bengaluru",
    communication: "Direct but calm",
    family: "Important, balanced",
    values: ["family", "kindness", "stability", "growth"],
    dealbreakers: ["casual intent", "smoking", "poor conflict repair"],
    confidence: 84
  }
];

let messages = [...starterMessages];
let replyIndex = 0;
let profileIndex = 0;

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const resetChat = document.querySelector("#reset-chat");
const extractProfile = document.querySelector("#extract-profile");
const refreshMatches = document.querySelector("#refresh-matches");
const matchList = document.querySelector("#match-list");
const createDemoDraft = document.querySelector("#create-demo-draft");
const saveDraft = document.querySelector("#save-draft");
const approveDraft = document.querySelector("#approve-draft");
const deleteDraft = document.querySelector("#delete-draft");
const draftStatus = document.querySelector("#draft-status");
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

let activeDraftId = null;

function renderMessages() {
  chatLog.innerHTML = "";
  messages.forEach((message) => {
    const bubble = document.createElement("div");
    bubble.className = `message ${message.role}`;
    bubble.textContent = message.text;
    chatLog.appendChild(bubble);
  });
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setProfile(profile) {
  document.querySelector("#profile-intent").textContent = profile.intent;
  document.querySelector("#profile-city").textContent = profile.city;
  document.querySelector("#profile-communication").textContent = profile.communication;
  document.querySelector("#profile-family").textContent = profile.family;
  document.querySelector("#confidence-text").textContent = `${profile.confidence}%`;
  document.querySelector("#confidence-meter").style.width = `${profile.confidence}%`;
  renderChips("#value-chips", profile.values);
  renderChips("#dealbreaker-chips", profile.dealbreakers);
}

function renderChips(selector, items) {
  const container = document.querySelector(selector);
  container.innerHTML = "";
  items.forEach((item) => {
    const chip = document.createElement("span");
    chip.textContent = item;
    container.appendChild(chip);
  });
}

async function loadMatches() {
  matchList.innerHTML = "";
  const loading = document.createElement("div");
  loading.className = "match-item";
  loading.textContent = "Loading suggestions...";
  matchList.appendChild(loading);

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
          <h3>${match.name}</h3>
          <p class="match-meta">${match.age} · ${match.city || "Location open"}</p>
        </div>
        <div class="score">${match.result.score}</div>
      </div>
      <p class="match-copy">${match.result.explanation}</p>
      <div class="breakdown">${breakdown}</div>
    `;
    matchList.appendChild(item);
  });
}

async function createAgentDraft() {
  const response = await fetch("/api/agent-submissions/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_provider: "chatgpt",
      agent_user_reference: "demo-user",
      display_name: "Aarav",
      age: 29,
      city: { value: "Bengaluru", source: "user_stated", confidence: 0.95 },
      relationship_intent: { value: "long_term", source: "user_stated", confidence: 0.92 },
      values: {
        values: ["family", "ambition", "emotional_stability"],
        source: "user_stated",
        confidence: 0.86
      },
      lifestyle: {
        values: ["fitness", "travel", "balanced_work"],
        source: "inferred",
        confidence: 0.72
      },
      communication_style: { value: "direct", source: "user_stated", confidence: 0.82 },
      family_expectations: {
        value: "medium involvement",
        source: "user_stated",
        confidence: 0.8
      },
      children_preference: { value: "wants_children", source: "inferred", confidence: 0.62 },
      dealbreakers: {
        values: ["smoking", "unclear intent"],
        source: "user_stated",
        confidence: 0.91
      },
      soft_preferences: {
        values: ["Bengaluru", "emotionally steady", "career oriented"],
        source: "inferred",
        confidence: 0.7
      },
      summary:
        "Looking for a serious relationship with someone emotionally steady, family-aware, and clear in communication."
    })
  });
  const data = await response.json();
  window.history.replaceState({}, "", data.review_url);
  await loadDraft(data.draft_id);
}

async function loadDraft(draftId) {
  const response = await fetch(`/api/drafts/${draftId}`);
  if (!response.ok) {
    setDraftStatus("Draft not found.", "deleted");
    return;
  }

  const draft = await response.json();
  activeDraftId = draft.id;
  fillDraftForm(draft);
  setDraftStatus(
    draft.status === "approved"
      ? "Approved. This profile can now enter matching."
      : `Draft ${draft.id} loaded. Review each field before approving.`,
    draft.status
  );
  setDraftButtons(draft.status);
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

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  messages.push({ role: "user", text });
  messages.push({
    role: "agent",
    text: agentReplies[replyIndex % agentReplies.length]
  });
  replyIndex += 1;
  chatInput.value = "";
  renderMessages();
});

resetChat.addEventListener("click", () => {
  messages = [...starterMessages];
  replyIndex = 0;
  renderMessages();
});

extractProfile.addEventListener("click", () => {
  profileIndex = (profileIndex + 1) % extractedProfiles.length;
  setProfile(extractedProfiles[profileIndex]);
});

refreshMatches.addEventListener("click", loadMatches);

createDemoDraft.addEventListener("click", createAgentDraft);

saveDraft.addEventListener("click", async () => {
  if (!activeDraftId) return;
  const response = await fetch(`/api/drafts/${activeDraftId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draftPatchFromForm())
  });
  const draft = await response.json();
  fillDraftForm(draft);
  setDraftStatus("Saved. Review is still required before matching.", "draft");
});

approveDraft.addEventListener("click", async () => {
  if (!activeDraftId) return;
  await fetch(`/api/drafts/${activeDraftId}/approve`, { method: "POST" });
  await loadDraft(activeDraftId);
  await loadMatches();
});

deleteDraft.addEventListener("click", async () => {
  if (!activeDraftId) return;
  await fetch(`/api/drafts/${activeDraftId}`, { method: "DELETE" });
  setDraftStatus("Deleted. This draft will not enter matching.", "deleted");
  activeDraftId = null;
  setDraftButtons("deleted");
});

const draftMatch = window.location.pathname.match(/^\/drafts\/([^/]+)$/);
if (draftMatch) {
  loadDraft(draftMatch[1]);
}

renderMessages();
setProfile(extractedProfiles[0]);
loadMatches();
