let messages = [];
let conversationId = null;
let activeDraftId = null;
let isSendingMessage = false;
let pendingAgentStyleSourceId = "";
let pendingDeleteConversationId = null;
let lastDeleteTrigger = null;
let supabaseClient = null;
let authSession = null;
let authRequired = false;
let datingBasicsComplete = null;

const contextImportPromptFallback = `I am using Omiryn to build a private personal profile about myself.

Please create a concise, privacy-safe self-profile about me based only on what you know from our past chats.
Focus on me as a person, not on my dating life. Include relationship details only if I clearly discussed them before.

Return sections:
1. Basic background and life context, only if known
2. Personality traits and temperament
3. Core values, priorities, and beliefs
4. Interests, hobbies, routines, and lifestyle patterns
5. Communication style and thinking style
6. Goals, ambitions, and current focus areas
7. Strengths, recurring challenges, and stress patterns
8. Preferences, dislikes, boundaries, and sensitivities
9. Important unknowns Omiryn should ask me

Rules:
- Do not invent facts.
- Mark uncertain points as uncertain.
- Do not infer romantic status, past relationships, sexual preferences, attraction patterns, or ideal partner unless explicitly known.
- Avoid exposing names, phone numbers, addresses, or private third-party details.
- Keep it under 1000 words.`;

const activeConversationStorageKey = "omiryn.activeConversationId";
const whatsappImportMaxChars = 1000000;

const routes = {
  interview: document.querySelector("#interview-screen"),
  review: document.querySelector("#review-screen"),
  matches: document.querySelector("#matches-screen"),
  profile: document.querySelector("#profile-screen"),
  usage: document.querySelector("#usage-screen")
};

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const sendMessage = document.querySelector("#send-message");
const agentStatus = document.querySelector("#agent-status");
const agentModelSelect = document.querySelector("#agent-model-select");
const agentModeSelect = document.querySelector("#agent-mode-select");
const agentToneSelect = document.querySelector("#agent-tone-select");
const agentStyleSelect = document.querySelector("#agent-style-select");
const resetChat = document.querySelector("#reset-chat");
const sidebarResetChat = document.querySelector("#sidebar-reset-chat");
const extractProfile = document.querySelector("#extract-profile");
const readinessScore = document.querySelector("#readiness-score");
const readinessMeter = document.querySelector("#readiness-meter");
const signalList = document.querySelector("#signal-list");
const usageSummary = document.querySelector("#usage-summary");
const sidebarUsageList = document.querySelector("#sidebar-usage-list");
const sideTabButtons = document.querySelectorAll("[data-side-tab]");
const sidePanels = document.querySelectorAll("[data-side-panel]");
const historyList = document.querySelector("#history-list");
const deleteSessionDialog = document.querySelector("#delete-session-dialog");
const deleteSessionId = document.querySelector("#delete-session-id");
const confirmDeleteSession = document.querySelector("#confirm-delete-session");
const cancelDeleteSession = document.querySelector("#cancel-delete-session");
const sidebarMessageCount = document.querySelector("#sidebar-message-count");
const sidebarConversationId = document.querySelector("#sidebar-conversation-id");
const activeMemoryCount = document.querySelector("#active-memory-count");
const activeMemoryList = document.querySelector("#active-memory-list");
const toneSuggestion = document.querySelector("#tone-suggestion");
const applyDetectedTone = document.querySelector("#apply-detected-tone");
const contextPrompt = document.querySelector("#context-prompt");
const copyContextPrompt = document.querySelector("#copy-context-prompt");
const contextSourceType = document.querySelector("#context-source-type");
const contextTitle = document.querySelector("#context-title");
const contextContent = document.querySelector("#context-content");
const saveContextSource = document.querySelector("#save-context-source");
const contextStatus = document.querySelector("#context-status");
const contextSourceList = document.querySelector("#context-source-list");
const whatsappSender = document.querySelector("#whatsapp-sender");
const whatsappStyleName = document.querySelector("#whatsapp-style-name");
const whatsappFiles = document.querySelector("#whatsapp-files");
const whatsappContent = document.querySelector("#whatsapp-content");
const saveWhatsappImport = document.querySelector("#save-whatsapp-import");
const whatsappStatus = document.querySelector("#whatsapp-status");
const whatsappImportLog = document.querySelector("#whatsapp-import-log");

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
const usageRateLimits = document.querySelector("#usage-rate-limits");
const usageRateLimitDetail = document.querySelector("#usage-rate-limit-detail");
const providerList = document.querySelector("#provider-list");
const rateLimitGrid = document.querySelector("#rate-limit-grid");
const usageMinuteBuckets = document.querySelector("#usage-minute-buckets");
const usageEvents = document.querySelector("#usage-events");
const usageTableRowLimit = 20;
const appShell = document.querySelector("#app-shell");
const authScreen = document.querySelector("#auth-screen");
const authScreenLogin = document.querySelector("#auth-screen-login");
const authScreenStatus = document.querySelector("#auth-screen-status");
const datingBasicsScreen = document.querySelector("#dating-basics-screen");
const datingBasicsForm = document.querySelector("#dating-basics-form");
const profileGender = document.querySelector("#profile-gender");
const profileInterestedIn = document.querySelector("#profile-interested-in");
const profileForm = document.querySelector("#profile-form");
const profileName = document.querySelector("#profile-name");
const profileEmail = document.querySelector("#profile-email");
const accountGender = document.querySelector("#account-gender");
const accountInterestedIn = document.querySelector("#account-interested-in");
const profileStatus = document.querySelector("#profile-status");
const profileStyleList = document.querySelector("#profile-style-list");
const profileMemoryList = document.querySelector("#profile-memory-list");
const datingBasicsStatus = document.querySelector("#dating-basics-status");
const saveDatingBasics = document.querySelector("#save-dating-basics");
const loginGoogle = document.querySelector("#login-google");
const logoutUser = document.querySelector("#logout-user");
const authUser = document.querySelector("#auth-user");
const authAvatar = document.querySelector("#auth-avatar");
const authEmail = document.querySelector("#auth-email");

const saveDraft = document.querySelector("#save-draft");
const approveDraft = document.querySelector("#approve-draft");
const deleteDraft = document.querySelector("#delete-draft");
const draftStatus = document.querySelector("#draft-status");
const warningList = document.querySelector("#warning-list");
const draftInputs = {
  name: document.querySelector("#draft-name"),
  gender: document.querySelector("#draft-gender"),
  interestedIn: document.querySelector("#draft-interested-in"),
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
  if (name === "profile") {
    loadProfilePage();
  }
}

function currentDraftIdFromPath() {
  const match = window.location.pathname.match(/^\/drafts\/([^/]+)$/);
  return match ? match[1] : null;
}

async function initializeAuth() {
  renderSignedOutAuth("Checking...");
  try {
    const response = await fetch("/api/auth/config");
    if (!response.ok) {
      throw new Error("Auth config unavailable.");
    }
    const config = await response.json();
    authRequired = Boolean(config.auth_required);
    if (!config.supabase_url || !config.supabase_anon_key) {
      renderSignedOutAuth("Auth not configured");
      renderAuthGate();
      return;
    }
    if (!window.supabase?.createClient) {
      throw new Error("Supabase client unavailable.");
    }

    supabaseClient = window.supabase.createClient(
      config.supabase_url,
      config.supabase_anon_key
    );
    const { data } = await supabaseClient.auth.getSession();
    authSession = data.session || null;
    renderAuthState();
    supabaseClient.auth.onAuthStateChange((_event, session) => {
      authSession = session || null;
      renderAuthState();
    });
  } catch (error) {
    renderSignedOutAuth(error.message);
    renderAuthGate(error.message);
  }
}

function renderAuthState() {
  const user = authSession?.user || null;
  if (!user) {
    datingBasicsComplete = null;
    renderSignedOutAuth("Continue with Google");
    renderAuthGate();
    return;
  }

  const email = user.email || "Signed in";
  if (authUser) {
    authUser.hidden = false;
  }
  if (authEmail) {
    authEmail.textContent = email;
  }
  if (authAvatar) {
    authAvatar.textContent = email.slice(0, 1).toUpperCase();
  }
  if (loginGoogle) {
    loginGoogle.hidden = true;
    loginGoogle.disabled = false;
  }
  if (logoutUser) {
    logoutUser.hidden = false;
    logoutUser.disabled = false;
  }
  renderAuthGate();
  loadDatingBasicsStatus();
  if (window.location.pathname === "/profile") {
    loadProfilePage();
  }
}

function renderSignedOutAuth(label) {
  if (authUser) {
    authUser.hidden = true;
  }
  if (loginGoogle) {
    loginGoogle.hidden = false;
    loginGoogle.disabled = label === "Checking..." || label === "Auth not configured";
    loginGoogle.textContent = label || "Continue with Google";
  }
  if (logoutUser) {
    logoutUser.hidden = true;
    logoutUser.disabled = false;
  }
  if (authScreenStatus) {
    authScreenStatus.textContent = label || "Sign in to continue.";
  }
}

function renderAuthGate(message) {
  const signedIn = Boolean(authSession?.user);
  const shouldAuthGate = authRequired && !signedIn;
  const shouldBasicsGate = signedIn && datingBasicsComplete === false;
  const shouldHideApp = shouldAuthGate || shouldBasicsGate;
  if (appShell) {
    appShell.hidden = shouldHideApp;
  }
  if (authScreen) {
    authScreen.hidden = !shouldAuthGate;
  }
  if (datingBasicsScreen) {
    datingBasicsScreen.hidden = !shouldBasicsGate;
  }
  if (authScreenLogin) {
    authScreenLogin.disabled = !supabaseClient;
  }
  if (authScreenStatus) {
    authScreenStatus.textContent = message || (signedIn ? "Signed in." : "Sign in to continue.");
  }
}

async function loadDatingBasicsStatus() {
  if (!authSession?.user) return;

  try {
    const response = await apiFetch("/api/me/dating-basics");
    if (!response.ok) {
      throw new Error("Could not load dating basics.");
    }
    const data = await response.json();
    datingBasicsComplete = Boolean(data.complete);
    if (data.profile) {
      if (profileGender) profileGender.value = data.profile.gender || "";
      if (profileInterestedIn) profileInterestedIn.value = data.profile.interested_in || "";
    }
    renderAuthGate();
    if (!datingBasicsComplete) {
      profileGender?.focus();
    }
  } catch (error) {
    datingBasicsComplete = false;
    if (datingBasicsStatus) {
      datingBasicsStatus.textContent = error.message;
    }
    renderAuthGate();
  }
}

function defaultInterestedIn(gender) {
  if (gender === "man") return "women";
  if (gender === "woman") return "men";
  return "everyone";
}

function updateInterestedInDefault() {
  if (!profileGender || !profileInterestedIn) return;
  profileInterestedIn.value = defaultInterestedIn(profileGender.value);
}

function updateAccountInterestedInDefault() {
  if (!accountGender || !accountInterestedIn) return;
  accountInterestedIn.value = defaultInterestedIn(accountGender.value);
}

async function saveDatingBasicsProfile(event) {
  event.preventDefault();
  if (!profileGender || !profileInterestedIn || !saveDatingBasics) return;

  if (!profileGender.value || !profileInterestedIn.value) {
    if (datingBasicsStatus) {
      datingBasicsStatus.textContent = "Choose both fields to continue.";
    }
    return;
  }

  saveDatingBasics.disabled = true;
  if (datingBasicsStatus) {
    datingBasicsStatus.textContent = "Saving...";
  }
  try {
    const response = await apiFetch("/api/me/dating-basics", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        gender: profileGender.value,
        interested_in: profileInterestedIn.value
      })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not save dating basics.");
    }
    datingBasicsComplete = true;
    if (accountGender) accountGender.value = profileGender.value;
    if (accountInterestedIn) accountInterestedIn.value = profileInterestedIn.value;
    if (datingBasicsStatus) {
      datingBasicsStatus.textContent = "";
    }
    renderAuthGate();
    focusChatInput();
  } catch (error) {
    if (datingBasicsStatus) {
      datingBasicsStatus.textContent = error.message;
    }
  } finally {
    saveDatingBasics.disabled = false;
  }
}

async function loadProfilePage() {
  if (!profileForm || !authSession?.user) return;

  if (profileStatus) {
    profileStatus.textContent = "Loading profile...";
  }
  try {
    const response = await apiFetch("/api/me/profile");
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not load profile.");
    }

    const profile = data.profile || {};
    if (profileName) profileName.value = profile.display_name || "";
    if (profileEmail) profileEmail.value = data.user?.email || "";
    if (accountGender) accountGender.value = profile.gender || "prefer_not_to_say";
    if (accountInterestedIn) accountInterestedIn.value = profile.interested_in || "everyone";
    renderProfileSources(profileStyleList, data.style_sources || [], "No learned text style yet.");
    renderProfileSources(profileMemoryList, data.memory_sources || [], "No imported memory yet.");
    if (profileStatus) {
      profileStatus.textContent = "Profile loaded.";
    }
  } catch (error) {
    if (profileStatus) {
      profileStatus.textContent = error.message;
    }
  }
}

async function saveProfilePage(event) {
  event.preventDefault();
  if (!profileForm || !accountGender || !accountInterestedIn) return;

  if (profileStatus) {
    profileStatus.textContent = "Saving profile...";
  }
  try {
    const response = await apiFetch("/api/me/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: profileName?.value.trim() || null,
        gender: accountGender.value,
        interested_in: accountInterestedIn.value
      })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not save profile.");
    }
    datingBasicsComplete = true;
    if (profileGender) profileGender.value = data.profile.gender || "";
    if (profileInterestedIn) profileInterestedIn.value = data.profile.interested_in || "";
    if (profileStatus) {
      profileStatus.textContent = "Profile saved.";
    }
  } catch (error) {
    if (profileStatus) {
      profileStatus.textContent = error.message;
    }
  }
}

function renderProfileSources(container, sources, emptyText) {
  if (!container) return;
  if (!sources.length) {
    container.innerHTML = `<div class="table-empty">${escapeHtml(emptyText)}</div>`;
    return;
  }
  container.innerHTML = sources
    .map((source) => `
      <article class="profile-source-item">
        <div>
          <strong>${escapeHtml(source.title)}</strong>
          <span>${escapeHtml(contextSourceLabel(source.source_type))} · ${formatNumber(source.content_length || 0)} chars</span>
        </div>
        <p>${escapeHtml(source.preview || "")}</p>
      </article>
    `)
    .join("");
}

async function signInWithGoogle() {
  if (!supabaseClient) return;

  loginGoogle.disabled = true;
  if (authScreenLogin) {
    authScreenLogin.disabled = true;
  }
  loginGoogle.textContent = "Opening Google...";
  if (authScreenStatus) {
    authScreenStatus.textContent = "Opening Google...";
  }
  const { error } = await supabaseClient.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: window.location.origin
    }
  });
  if (error) {
    loginGoogle.disabled = false;
    if (authScreenLogin) {
      authScreenLogin.disabled = false;
    }
    loginGoogle.textContent = "Continue with Google";
    if (authScreenStatus) {
      authScreenStatus.textContent = error.message;
    }
  }
}

async function signOutUser() {
  if (!supabaseClient) return;

  logoutUser.disabled = true;
  await supabaseClient.auth.signOut();
  authSession = null;
  renderAuthState();
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = authSession?.access_token;
  if (token && String(url).startsWith("/api/")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(url, {
    ...options,
    headers
  });
}

function storedConversationId() {
  try {
    return window.localStorage.getItem(activeConversationStorageKey);
  } catch {
    return null;
  }
}

function rememberConversation(id) {
  conversationId = id;
  try {
    window.localStorage.setItem(activeConversationStorageKey, id);
  } catch {
    // Browser storage can be unavailable in private or restricted contexts.
  }
}

function forgetStoredConversation() {
  try {
    window.localStorage.removeItem(activeConversationStorageKey);
  } catch {
    // Nothing to clear when browser storage is unavailable.
  }
}

async function startConversation() {
  await loadAgentStatus();
  chatInput.disabled = true;
  if (extractProfile) extractProfile.disabled = true;
  const response = await apiFetch("/api/agent/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_model: selectedAgentModel(),
      agent_mode: selectedAgentMode(),
      agent_tone: selectedAgentTone(),
      agent_style_source_id: selectedAgentStyleSourceId()
    })
  });
  const conversation = await response.json();
  hydrateConversation(conversation);
  return conversation;
}

async function restoreOrStartConversation() {
  await loadAgentStatus();
  const savedConversationId = storedConversationId();
  if (!savedConversationId) {
    prepareEmptyConversation();
    await loadConversationHistory();
    return;
  }

  chatInput.disabled = true;
  if (extractProfile) extractProfile.disabled = true;
  try {
    const response = await apiFetch(`/api/agent/conversations/${savedConversationId}`);
    if (!response.ok) {
      throw new Error("Stored conversation was not found.");
    }
    const conversation = await response.json();
    hydrateConversation(conversation);
  } catch {
    forgetStoredConversation();
    prepareEmptyConversation();
    await loadConversationHistory();
  }
}

function prepareEmptyConversation() {
  conversationId = null;
  messages = [];
  pendingAgentStyleSourceId = "";
  chatInput.disabled = false;
  if (extractProfile) extractProfile.disabled = true;
  renderMessages();
  updateReadiness();
  updateSidebarMeta();
  loadContextImportPrompt();
  renderContextSources([]);
  renderActiveMemory([]);
  renderReplyStyleOptions([]);
  focusChatInput();
}

function hydrateConversation(conversation) {
  rememberConversation(conversation.id);
  messages = conversation.messages;
  if (conversation.agent_model && agentModelSelect) {
    agentModelSelect.value = conversation.agent_model;
  }
  if (conversation.agent_mode && agentModeSelect) {
    agentModeSelect.value = conversation.agent_mode;
  }
  if (conversation.agent_tone && agentToneSelect) {
    agentToneSelect.value = conversation.agent_tone;
  }
  pendingAgentStyleSourceId = conversation.agent_style_source_id || "";
  if (agentStyleSelect) {
    agentStyleSelect.value = pendingAgentStyleSourceId;
  }
  updateAgentStatusModel();
  chatInput.disabled = false;
  if (extractProfile) extractProfile.disabled = false;
  renderMessages();
  updateReadiness();
  updateSidebarMeta();
  loadContextImportPrompt();
  loadContextSources();
  loadDetectedTone();
  loadAgentUsage();
  loadConversationHistory();
  focusChatInput();
}

async function loadAgentStatus() {
  if (!agentStatus) return;

  try {
    const response = await apiFetch("/api/agent/status");
    const status = await response.json();
    const provider = titleCase(status.provider || "unknown");
    const model = status.model || "no model";
    configureModelSelect(status.available_models || [], model);
    agentStatus.dataset.provider = provider;
    updateAgentStatusModel();
  } catch {
    agentStatus.textContent = "Agent status unavailable";
  }
}

function configureModelSelect(models, selectedModel) {
  if (!agentModelSelect) return;

  const currentValue = agentModelSelect.value || selectedModel;
  agentModelSelect.innerHTML = "";
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    agentModelSelect.appendChild(option);
  });

  if (!models.length) {
    const option = document.createElement("option");
    option.value = selectedModel;
    option.textContent = selectedModel;
    agentModelSelect.appendChild(option);
  }

  agentModelSelect.value = models.includes(currentValue) ? currentValue : selectedModel;
}

function selectedAgentModel() {
  return agentModelSelect ? agentModelSelect.value : null;
}

function selectedAgentMode() {
  return agentModeSelect ? agentModeSelect.value : "know_me";
}

function selectedAgentTone() {
  return agentToneSelect ? agentToneSelect.value : "auto";
}

function selectedAgentStyleSourceId() {
  return agentStyleSelect ? agentStyleSelect.value || null : null;
}

function updateAgentStatusModel() {
  if (!agentStatus) return;

  const provider = agentStatus.dataset.provider || "Agent";
  agentStatus.textContent = `${provider} · ${agentModeLabel(selectedAgentMode())} · ${agentToneLabel(selectedAgentTone())} · ${agentStyleLabel()} · ${selectedAgentModel() || "no model"}`;
}

async function updateConversationModel() {
  if (!conversationId) return;

  const requestedStyleSourceId = selectedAgentStyleSourceId();
  pendingAgentStyleSourceId = requestedStyleSourceId || "";

  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_model: selectedAgentModel(),
        agent_mode: selectedAgentMode(),
        agent_tone: selectedAgentTone(),
        agent_style_source_id: requestedStyleSourceId
      })
    });
    const conversation = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(conversation.detail, "Could not update agent settings."));
    }
    if (conversation.agent_model && agentModelSelect) {
      agentModelSelect.value = conversation.agent_model;
    }
    if (conversation.agent_mode && agentModeSelect) {
      agentModeSelect.value = conversation.agent_mode;
    }
    if (conversation.agent_tone && agentToneSelect) {
      agentToneSelect.value = conversation.agent_tone;
    }
    pendingAgentStyleSourceId = conversation.agent_style_source_id || "";
    if (agentStyleSelect) {
      agentStyleSelect.value = pendingAgentStyleSourceId;
    }
    updateAgentStatusModel();
    loadDetectedTone();
  } catch (error) {
    if (agentStatus) {
      agentStatus.textContent = error.message;
    }
  }
}

function agentModeLabel(mode) {
  const labels = {
    know_me: "Know me",
    coach_me: "Coach me",
    match_me: "Match me",
    talk_like_me: "Talk like me"
  };
  return labels[mode] || "Know me";
}

function agentToneLabel(tone) {
  const labels = {
    auto: "Auto tone",
    casual: "Casual",
    warm: "Warm",
    formal: "Formal",
    direct: "Direct",
    playful: "Playful"
  };
  return labels[tone] || "Auto tone";
}

function agentStyleLabel() {
  if (!agentStyleSelect || !agentStyleSelect.value) {
    return "Default style";
  }
  const selected = agentStyleSelect.options[agentStyleSelect.selectedIndex];
  return selected?.textContent || "Saved style";
}

function titleCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function renderMessages() {
  chatLog.innerHTML = "";
  messages.forEach((message, index) => {
    const bubble = document.createElement("div");
    bubble.className = `message ${message.role === "assistant" ? "agent" : "user"}`;
    if (message.quality === "low_information") {
      bubble.classList.add("low-information");
    }

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
  if (name === "context") {
    loadContextImportPrompt();
    loadContextSources();
  }
  if (name === "history") {
    loadConversationHistory();
  }
}

async function loadConversationHistory() {
  if (!historyList) return;

  try {
    const response = await apiFetch("/api/agent/conversations");
    if (!response.ok) {
      throw new Error("Could not load chat history.");
    }
    const data = await response.json();
    renderConversationHistory(data.conversations || []);
  } catch (error) {
    historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderConversationHistory(conversations) {
  if (!historyList) return;

  const visibleConversations = conversations.filter(
    (conversation) =>
      conversation.id === conversationId ||
      conversation.user_message_count > 0 ||
      conversation.context_source_count > 0
  );

  if (!visibleConversations.length) {
    historyList.innerHTML = '<div class="history-empty">No saved conversations yet.</div>';
    return;
  }

  historyList.innerHTML = "";
  visibleConversations.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "history-item";
    item.classList.toggle("active", conversation.id === conversationId);
    item.setAttribute("role", "button");
    item.tabIndex = 0;
    const updatedAt = conversation.updated_at
      ? new Date(conversation.updated_at).toLocaleString()
      : "No timestamp";
    item.innerHTML = `
      <div class="history-item-copy">
        <strong>Session ${escapeHtml(conversation.id.slice(0, 8))}</strong>
        <span>${formatNumber(conversation.message_count || 0)} messages · ${formatNumber(conversation.context_source_count || 0)} context</span>
        <small>${escapeHtml(updatedAt)}</small>
      </div>
      <button class="history-delete" type="button" aria-label="Delete session ${escapeHtml(conversation.id.slice(0, 8))}" title="Delete session">
        <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
          <path d="M9 3h6l1 2h4v2H4V5h4l1-2Z"></path>
          <path d="M6 9h12l-.8 11H6.8L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z"></path>
        </svg>
      </button>
    `;
    item.addEventListener("click", () => {
      loadConversation(conversation.id).catch((error) => {
        historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
      });
    });
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      loadConversation(conversation.id).catch((error) => {
        historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
      });
    });
    item.querySelector(".history-delete")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openDeleteSessionDialog(conversation.id, event.currentTarget);
    });
    historyList.appendChild(item);
  });
}

function openDeleteSessionDialog(id, trigger) {
  if (!id) return;

  pendingDeleteConversationId = id;
  lastDeleteTrigger = trigger || null;
  if (deleteSessionId) {
    deleteSessionId.textContent = `Session ${id.slice(0, 8)}`;
  }
  if (deleteSessionDialog) {
    deleteSessionDialog.hidden = false;
  }
  confirmDeleteSession?.focus();
}

function closeDeleteSessionDialog() {
  if (deleteSessionDialog) {
    deleteSessionDialog.hidden = true;
  }
  pendingDeleteConversationId = null;
  if (lastDeleteTrigger && document.contains(lastDeleteTrigger)) {
    lastDeleteTrigger.focus();
  }
  lastDeleteTrigger = null;
}

async function confirmDeleteConversation() {
  const id = pendingDeleteConversationId;
  if (!id) return;

  confirmDeleteSession.disabled = true;
  cancelDeleteSession.disabled = true;

  const response = await apiFetch(`/api/agent/conversations/${id}`, { method: "DELETE" });
  confirmDeleteSession.disabled = false;
  cancelDeleteSession.disabled = false;

  if (!response.ok) {
    if (deleteSessionId) {
      deleteSessionId.textContent = "Could not delete. Refresh and try again.";
    }
    return;
  }

  closeDeleteSessionDialog();
  if (id === conversationId) {
    forgetStoredConversation();
    prepareEmptyConversation();
  }
  await loadConversationHistory();
}

async function loadConversation(id) {
  if (!id || id === conversationId) return;

  chatInput.disabled = true;
  if (extractProfile) extractProfile.disabled = true;
  const response = await apiFetch(`/api/agent/conversations/${id}`);
  if (!response.ok) {
    chatInput.disabled = false;
    if (extractProfile) extractProfile.disabled = false;
    throw new Error("Could not load that conversation.");
  }
  const conversation = await response.json();
  hydrateConversation(conversation);
}

async function loadContextImportPrompt() {
  if (!contextPrompt || contextPrompt.dataset.loaded === "true") return;

  contextPrompt.value = contextPrompt.value.trim() || contextImportPromptFallback;
  try {
    const response = await apiFetch("/api/context-import-prompt");
    if (!response.ok) {
      throw new Error("Prompt API unavailable.");
    }
    const data = await response.json();
    contextPrompt.value = data.prompt || contextImportPromptFallback;
    contextPrompt.dataset.loaded = "true";
  } catch {
    contextPrompt.value = contextImportPromptFallback;
  }
}

async function copyContextImportPrompt() {
  if (!contextPrompt) return;

  try {
    await navigator.clipboard.writeText(contextPrompt.value);
    setContextStatus("Prompt copied.");
  } catch {
    contextPrompt.select();
    document.execCommand("copy");
    setContextStatus("Prompt copied.");
  }
}

async function loadContextSources() {
  if (!conversationId) {
    renderContextSources([]);
    renderActiveMemory([]);
    renderReplyStyleOptions([]);
    return;
  }

  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/context-sources`);
    if (response.status === 404) {
      throw new Error("Restart the app server to enable context import.");
    }
    if (!response.ok) {
      throw new Error("Could not load imported context.");
    }
    const data = await response.json();
    renderContextSources(data.sources || []);
    renderActiveMemory(data.sources || []);
    renderReplyStyleOptions(data.sources || []);
    loadDetectedTone();
  } catch (error) {
    setContextStatus(error.message);
  }
}

async function loadDetectedTone() {
  if (!conversationId || !toneSuggestion) return;

  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/tone`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Tone unavailable.");
    }
    const detected = data.detected_tone || {};
    toneSuggestion.textContent = `Detected: ${agentToneLabel(detected.tone)} · ${Math.round((detected.confidence || 0) * 100)}% · Selected: ${agentToneLabel(data.selected_tone)}`;
    if (applyDetectedTone) {
      applyDetectedTone.hidden = !detected.tone || data.selected_tone !== "auto";
      applyDetectedTone.dataset.tone = detected.tone || "";
    }
  } catch {
    toneSuggestion.textContent = "Detected tone unavailable.";
    if (applyDetectedTone) {
      applyDetectedTone.hidden = true;
      applyDetectedTone.dataset.tone = "";
    }
  }
}

async function applyDetectedToneSelection() {
  const tone = applyDetectedTone?.dataset.tone;
  if (!tone || !agentToneSelect) return;

  agentToneSelect.value = tone;
  await updateConversationModel();
}

async function saveConversationContextSource() {
  if (!contextContent || !saveContextSource) return;
  if (!conversationId) {
    setContextStatus("Send one message first, then save context to that session.");
    return;
  }

  const content = contextContent.value.trim();
  if (content.length < 20) {
    setContextStatus("Paste at least a few sentences before saving.");
    return;
  }

  saveContextSource.disabled = true;
  setContextStatus("Saving context...");
  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/context-sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_type: contextSourceType?.value || "llm_profile",
        title: contextTitle?.value.trim() || "Imported context",
        content
      })
    });
    const data = await response.json();
    if (response.status === 404) {
      throw new Error("Restart the app server to enable context import.");
    }
    if (!response.ok) {
      throw new Error(data.detail || "Could not save context.");
    }
    contextContent.value = "";
    setContextStatus("Context saved. Future replies can use it.");
    await loadContextSources();
  } catch (error) {
    setContextStatus(error.message);
  } finally {
    saveContextSource.disabled = false;
  }
}

async function saveWhatsappStyleImport() {
  if (!saveWhatsappImport) return;
  if (!conversationId) {
    setWhatsappStatus("Send one message first, then import a text style.", "error");
    return;
  }

  let imports;
  try {
    imports = await whatsappImportPayloads();
  } catch (error) {
    setWhatsappStatus(error.message, "error");
    return;
  }

  if (!imports.length) {
    setWhatsappStatus("Choose WhatsApp .txt files or paste one text export before importing.", "error");
    return;
  }

  saveWhatsappImport.disabled = true;
  renderWhatsappImportLog([]);
  setWhatsappStatus(`Analyzing ${imports.length} WhatsApp export${imports.length === 1 ? "" : "s"}...`, "working");
  try {
    const imported = [];
    for (let index = 0; index < imports.length; index += 1) {
      const item = imports[index];
      setWhatsappStatus(`Importing ${index + 1}/${imports.length}: ${item.title}`, "working");
      const source = await importWhatsappPayload(item);
      imported.push(source);
      renderWhatsappImportLog(imported);
    }

    if (whatsappFiles) {
      whatsappFiles.value = "";
    }
    if (whatsappStyleName) {
      whatsappStyleName.value = "";
    }
    if (whatsappContent) {
      whatsappContent.value = "";
    }
    pendingAgentStyleSourceId = imported[0]?.id || pendingAgentStyleSourceId;
    await loadContextSources();
    if (agentStyleSelect && imported[0]?.id) {
      agentStyleSelect.value = imported[0].id;
      pendingAgentStyleSourceId = imported[0].id;
      await updateConversationModel();
    }
    setWhatsappStatus(
      `${imports.length} text style${imports.length === 1 ? "" : "s"} imported and selected.`,
      "success"
    );
    await loadDetectedTone();
  } catch (error) {
    setWhatsappStatus(error.message, "error");
  } finally {
    saveWhatsappImport.disabled = false;
  }
}

async function whatsappImportPayloads() {
  const senderToLearn = whatsappSender?.value.trim() || "";
  if (!senderToLearn) {
    throw new Error("Enter the exact WhatsApp sender to learn, for example Sanjay.");
  }

  const files = Array.from(whatsappFiles?.files || []);
  if (files.length) {
    return Promise.all(files.map(whatsappPayloadFromFile));
  }

  const content = whatsappContent?.value.trim() || "";
  if (!content) return [];
  validateWhatsappImportSize(content, "Pasted export");
  const styleName = normalizedWhatsappStyleName("Pasted export");
  return [
    {
      title: styleName,
      style_name: styleName,
      content
    }
  ];
}

async function whatsappPayloadFromFile(file) {
  if (file.size > whatsappImportMaxChars * 4) {
    throw new Error(`${file.name} is too large for v1.`);
  }

  const content = (await file.text()).trim();
  validateWhatsappImportSize(content, file.name);
  const fileLabel = file.name.replace(/\.[^.]+$/, "");
  const styleName = normalizedWhatsappStyleName(fileLabel);
  return {
    title: styleName,
    style_name: styleName,
    content
  };
}

function normalizedWhatsappStyleName(fallbackLabel) {
  const rawName = whatsappStyleName?.value.trim() || whatsappSender?.value.trim() || fallbackLabel;
  return rawName.toLowerCase().endsWith("style") ? rawName : `${rawName}-style`;
}

function validateWhatsappImportSize(content, label) {
  if (content.length < 50) {
    throw new Error(`${label} does not look like a WhatsApp text export.`);
  }
  if (content.length > whatsappImportMaxChars) {
    throw new Error(
      `${label} is too large for v1. Limit is ${formatNumber(whatsappImportMaxChars)} characters.`
    );
  }
}

async function importWhatsappPayload(item) {
  const response = await apiFetch(`/api/agent/conversations/${conversationId}/whatsapp-import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: item.title,
      user_sender: whatsappSender?.value.trim(),
      style_name: item.style_name,
      style_kind: "friend_style",
      content: item.content
    })
  });
  const data = await response.json();
  if (response.status === 404) {
    throw new Error("Restart the app server to enable WhatsApp import.");
  }
  if (!response.ok) {
    throw new Error(apiErrorMessage(data.detail, `Could not import ${item.title}.`));
  }
  return data;
}

function renderContextSources(sources) {
  if (!contextSourceList) return;

  if (!sources.length) {
    contextSourceList.innerHTML = "";
    setContextStatus("No imported context yet.");
    return;
  }

  contextSourceList.innerHTML = sources
    .map((source) => `
      <div class="context-source-item">
        <strong>${escapeHtml(source.title)}</strong>
        <span>${escapeHtml(contextSourceLabel(source.source_type))} · ${formatNumber(source.content_length)} chars</span>
      </div>
    `)
    .join("");
  setContextStatus(`${sources.length} context source${sources.length === 1 ? "" : "s"} saved.`);
}

function contextSourceLabel(sourceType) {
  const labels = {
    llm_profile: "LLM profile",
    chat_export: "Short chat summary",
    manual_notes: "Manual notes",
    whatsapp_chat: "My WhatsApp style",
    friend_style: "Friend text style"
  };
  return labels[sourceType] || sourceType || "Context";
}

function renderReplyStyleOptions(sources) {
  if (!agentStyleSelect) return;

  const styleSources = sources.filter((source) =>
    ["whatsapp_chat", "friend_style"].includes(source.source_type)
  );
  const currentValue = agentStyleSelect.value || "";
  const activeValue = currentValue || pendingAgentStyleSourceId || "";
  agentStyleSelect.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "Default";
  agentStyleSelect.appendChild(defaultOption);

  styleSources.forEach((source) => {
    const option = document.createElement("option");
    option.value = source.id;
    option.textContent = source.title;
    agentStyleSelect.appendChild(option);
  });

  const hasActiveValue = styleSources.some((source) => source.id === activeValue);
  agentStyleSelect.value = hasActiveValue ? activeValue : "";
  pendingAgentStyleSourceId = agentStyleSelect.value;
  updateAgentStatusModel();
}

function handleAgentStyleSelectionChange() {
  pendingAgentStyleSourceId = selectedAgentStyleSourceId() || "";
  updateConversationModel();
}

function renderActiveMemory(sources) {
  if (!activeMemoryList || !activeMemoryCount) return;

  activeMemoryCount.textContent = `${sources.length} source${sources.length === 1 ? "" : "s"}`;
  if (!sources.length) {
    activeMemoryList.innerHTML = '<div class="memory-empty">No imported memory yet.</div>';
    return;
  }

  activeMemoryList.innerHTML = sources
    .slice(0, 5)
    .map((source) => {
      const label = contextSourceLabel(source.source_type);
      return `
        <div class="memory-item">
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(source.title)} · ${formatNumber(source.content_length)} chars</span>
        </div>
      `;
    })
    .join("");
}

function setContextStatus(message) {
  if (contextStatus) {
    contextStatus.textContent = message;
  }
}

function setWhatsappStatus(message, state = "") {
  if (whatsappStatus) {
    whatsappStatus.textContent = message;
    whatsappStatus.dataset.state = state;
  }
}

function updateWhatsappFileSelectionStatus() {
  const count = whatsappFiles?.files?.length || 0;
  if (!count) {
    setWhatsappStatus(
      "V1 limit: text-only exports up to 1,000,000 characters per file. Raw chat is not saved as context."
    );
    renderWhatsappImportLog([]);
    return;
  }

  setWhatsappStatus(`${count} WhatsApp .txt file${count === 1 ? "" : "s"} selected. Click Import WhatsApp style.`, "working");
}

function renderWhatsappImportLog(sources) {
  if (!whatsappImportLog) return;

  whatsappImportLog.innerHTML = sources
    .map(
      (source) => `
        <div class="whatsapp-import-item">
          <strong>${escapeHtml(source.title || "WhatsApp style")}</strong>
          <span>Saved · ${formatNumber(source.content_length || 0)} chars summary</span>
        </div>
      `
    )
    .join("");
}

function apiErrorMessage(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || item.message || String(item)).join(" ");
  }
  return detail.msg || detail.message || fallback;
}

function updateReadiness() {
  if (!readinessScore || !readinessMeter || !signalList) return;

  const userMessageCount = messages.filter(
    (message) => message.role === "user" && message.quality !== "low_information"
  ).length;
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
  if (!text) return;

  messages.push({ role: "user", content: text });
  chatInput.value = "";
  isSendingMessage = true;
  renderMessages();
  updateReadiness();
  focusChatInput();

  try {
    if (!conversationId) {
      const conversation = await startConversation();
      messages = [...(conversation.messages || []), { role: "user", content: text }];
      renderMessages();
      updateReadiness();
    }
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/messages`, {
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
    loadDetectedTone();
    loadConversationHistory();
    focusChatInput();
  }
}

async function loadAgentUsage() {
  if (!usageSummary || !conversationId) return;

  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/usage`);
    const data = await response.json();
    const summary = data.summary || {};
    const events = data.events || [];
    const cost = summary.estimated_cost_usd
      ? ` · $${summary.estimated_cost_usd.toFixed(6)}`
      : "";
    const inrCost = summary.estimated_cost_inr
      ? ` / ₹${summary.estimated_cost_inr.toFixed(4)}`
      : "";
    usageSummary.innerHTML = `
      <div class="sidebar-usage-total">
        <strong>${formatNumber(summary.total_tokens || 0)}</strong>
        <span>total tokens</span>
      </div>
      <div>${formatNumber(summary.request_count || 0)} requests · ${formatNumber(summary.successful_request_count || 0)} successful</div>
      <div>${formatNumber(summary.prompt_tokens || 0)} input / ${formatNumber(summary.completion_tokens || 0)} output${cost}${inrCost}</div>
    `;
    renderSidebarUsageEvents(events);
  } catch {
    usageSummary.textContent = "Usage unavailable";
    renderSidebarUsageEvents([]);
  }
}

function renderSidebarUsageEvents(events) {
  if (!sidebarUsageList) return;

  if (!events.length) {
    sidebarUsageList.innerHTML = '<div class="sidebar-usage-empty">No calls yet.</div>';
    return;
  }

  sidebarUsageList.innerHTML = events
    .slice(0, 6)
    .map((event, index) => {
      const createdAt = event.created_at ? new Date(event.created_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit"
      }) : "";
      const tokenText = event.total_tokens
        ? `${formatNumber(event.prompt_tokens || 0)} in / ${formatNumber(event.completion_tokens || 0)} out`
        : "tokens unavailable";
      const totalText = event.total_tokens ? formatNumber(event.total_tokens) : "-";
      const status = event.success ? "ok" : "failed";
      return `
        <div class="sidebar-usage-item ${status}">
          <div>
            <strong>#${events.length - index} ${escapeHtml(event.request_kind || "agent_call")}</strong>
            <span>${escapeHtml(createdAt)} · ${escapeHtml(event.model || event.provider || "-")}</span>
          </div>
          <div class="sidebar-usage-tokens">
            <strong>${totalText}</strong>
            <span>${tokenText}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

function focusChatInput() {
  window.requestAnimationFrame(() => {
    chatInput.focus();
  });
}

async function extractConversationDraft() {
  if (!conversationId) return;

  if (extractProfile) {
    extractProfile.disabled = true;
    extractProfile.textContent = "Extracting...";
  }
  await loadAgentUsage();
  const response = await apiFetch(`/api/agent/conversations/${conversationId}/extract`, {
    method: "POST"
  });
  const data = await response.json();
  if (extractProfile) {
    extractProfile.disabled = false;
    extractProfile.textContent = "Extract review draft";
  }
  await loadAgentUsage();

  if (data.review_url) {
    window.location.href = data.review_url;
  }
}

async function loadDraft(draftId) {
  const response = await apiFetch(`/api/drafts/${draftId}`);
  if (!response.ok) {
    setDraftStatus("Draft not found.", "deleted");
    setDraftButtons("deleted");
    return;
  }

  const draft = await response.json();
  activeDraftId = draft.id;
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
  draftInputs.gender.value = submission.gender?.value || "unknown";
  draftInputs.interestedIn.value = submission.interested_in?.value || "unknown";
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
    gender: draftInputs.gender.value,
    interested_in: draftInputs.interestedIn.value,
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
  const response = await apiFetch(`/api/drafts/${activeDraftId}`, {
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
  await apiFetch(`/api/drafts/${activeDraftId}/approve`, { method: "POST" });
  await loadDraft(activeDraftId);
  window.location.href = "/matches";
}

async function deleteCurrentDraft() {
  if (!activeDraftId) return;
  await apiFetch(`/api/drafts/${activeDraftId}`, { method: "DELETE" });
  activeDraftId = null;
  setDraftStatus("Deleted. This draft will not enter matching.", "deleted");
  setDraftButtons("deleted");
}

async function loadMatches() {
  matchList.innerHTML = '<div class="loading-row">Loading suggestions...</div>';
  const response = await apiFetch("/api/demo/matches");
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
  if (usageMinuteBuckets) {
    usageMinuteBuckets.innerHTML = '<tr><td colspan="4">Loading usage...</td></tr>';
  }

  try {
    const response = await apiFetch("/api/agent/usage");
    const data = await response.json();
    renderUsageSummary(data.summary || {});
    renderProviderMix(data.events || []);
    renderGroqRateLimitHealth(data.events || [], data.limits || {});
    renderTokensByMinute(data.events || []);
    renderUsageEvents(data.events || []);
  } catch (error) {
    usageEvents.innerHTML = `<tr><td colspan="6">Could not load usage. ${escapeHtml(error.message)}</td></tr>`;
    providerList.innerHTML = '<div class="loading-row">Usage unavailable.</div>';
    if (rateLimitGrid) {
      rateLimitGrid.innerHTML = '<div class="table-empty">Rate-limit data unavailable.</div>';
    }
    if (usageMinuteBuckets) {
      usageMinuteBuckets.innerHTML = '<tr><td colspan="4">Usage unavailable.</td></tr>';
    }
  }
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

  if (!groqEvents.length) {
    rateLimitGrid.innerHTML = '<div class="table-empty">No Groq calls logged yet.</div>';
    return;
  }

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

function groqRateLimitHeaders(event) {
  return event.raw_usage?.rate_limit || null;
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
    .map(
      (row) => `
        <tr>
          <td>${formatMinute(row.minute)}</td>
          <td class="mono">${formatNumber(row.calls)}</td>
          <td class="mono">${formatNumber(row.totalTokens)}</td>
          <td class="mono">${formatNumber(row.promptTokens)} in / ${formatNumber(row.completionTokens)} out</td>
        </tr>
      `
    )
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

function formatMinute(value) {
  return value.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
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
resetChat?.addEventListener("click", startConversation);
sidebarResetChat?.addEventListener("click", startConversation);
extractProfile?.addEventListener("click", extractConversationDraft);
saveDraft.addEventListener("click", saveDraftEdits);
approveDraft.addEventListener("click", approveCurrentDraft);
deleteDraft.addEventListener("click", deleteCurrentDraft);
refreshMatches.addEventListener("click", loadMatches);
refreshUsage.addEventListener("click", loadUsageDashboard);
sideTabButtons.forEach((button) => {
  button.addEventListener("click", () => showSidePanel(button.dataset.sideTab));
});
agentModelSelect.addEventListener("change", updateConversationModel);
agentModeSelect?.addEventListener("change", updateConversationModel);
agentToneSelect?.addEventListener("change", updateConversationModel);
agentStyleSelect?.addEventListener("change", handleAgentStyleSelectionChange);
applyDetectedTone?.addEventListener("click", applyDetectedToneSelection);
copyContextPrompt?.addEventListener("click", copyContextImportPrompt);
saveContextSource?.addEventListener("click", saveConversationContextSource);
saveWhatsappImport?.addEventListener("click", saveWhatsappStyleImport);
whatsappFiles?.addEventListener("change", updateWhatsappFileSelectionStatus);
confirmDeleteSession?.addEventListener("click", confirmDeleteConversation);
cancelDeleteSession?.addEventListener("click", closeDeleteSessionDialog);
loginGoogle?.addEventListener("click", signInWithGoogle);
authScreenLogin?.addEventListener("click", signInWithGoogle);
logoutUser?.addEventListener("click", signOutUser);
profileGender?.addEventListener("change", updateInterestedInDefault);
accountGender?.addEventListener("change", updateAccountInterestedInDefault);
datingBasicsForm?.addEventListener("submit", saveDatingBasicsProfile);
profileForm?.addEventListener("submit", saveProfilePage);
deleteSessionDialog?.addEventListener("click", (event) => {
  if (event.target === deleteSessionDialog) {
    closeDeleteSessionDialog();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && deleteSessionDialog && !deleteSessionDialog.hidden) {
    closeDeleteSessionDialog();
  }
});

initializeAuth();

const draftId = currentDraftIdFromPath();
if (draftId) {
  showScreen("review");
  loadDraft(draftId);
} else if (window.location.pathname === "/matches") {
  showScreen("matches");
  loadMatches();
} else if (window.location.pathname === "/profile") {
  showScreen("profile");
} else if (window.location.pathname === "/usage") {
  showScreen("usage");
  loadUsageDashboard();
} else {
  showScreen("interview");
  restoreOrStartConversation();
}
