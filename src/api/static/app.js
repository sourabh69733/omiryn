let messages = [];
let conversationId = null;
let activeDraftId = null;
let isSendingMessage = false;
let isAwaitingAgentReply = false;
let isAssistantTyping = false;
let isConversationLoading = false;
let pendingContextSourceIds = [];
let pendingDeleteConversationId = null;
let pendingDeleteContextSource = null;
let lastDeleteTrigger = null;
let lastDeleteMemoryTrigger = null;
let currentAgentName = null;
let profileFactsById = new Map();
let profileFactList = [];
let profileFactGroupsData = {};
let rawProfileDataPoints = [];
let activeDataPointFeedbackId = null;
let lastEvidenceTrigger = null;
let pendingMessageHighlightIndex = null;
let supabaseClient = null;
let authSession = null;
let authRequired = false;
let authProvider = "none";
let profileDebugDataEnabled = false;
let datingBasicsComplete = null;
let onboardingStep = 1;
let activeFeedbackMessageIndex = null;
let feedbackPositionFrame = null;
let feedbackLoadedConversationId = null;
let feedbackLoadPromise = null;
let revealedFeedbackMessageIndex = null;
let accountProfilePhotoUrls = [];
let pendingAccountPhotoSlot = 0;
let onboardingProfilePhotoFiles = Array(4).fill(null);
let pendingOnboardingPhotoSlot = 0;
let indiaLocations = null;
const messageFeedbackState = new Map();
const typingSpeedProfiles = {
  feminine: { wpm: 38 },
  masculine: { wpm: 34 },
  neutral: { wpm: 36 }
};
const userTypingProfile = {
  wpm: null,
  samples: 0,
  draftStartedAt: null,
  lastInputLength: 0
};
const typingTimeScale = 0.22;
const minTypingDelayMs = 650;
const maxTypingDelayMs = 5200;
const minThinkingDelayMs = 700;
const maxThinkingDelayMs = 3600;

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
const agentNamePools = {
  women: ["Annie", "Mira", "Kiara", "Aisha", "Naina", "Riya", "Sana", "Meera"],
  men: ["Kabir", "Billy", "Aarav", "Ishaan", "Veer"],
  everyone: ["Mira", "Annie", "Kabir", "Kiara", "Billy", "Naina", "Aarav", "Sana"]
};
const agentAvatarAssets = {
  women: [
    "/static/assets/agent_avatar/saree_female.png",
    "/static/assets/agent_avatar/suite_female.png"
  ],
  men: [
    "/static/assets/agent_avatar/jacket_male.png",
    "/static/assets/agent_avatar/kurta_male.png"
  ]
};
const feedbackReactions = [
  { rating: "good", label: "Good", icon: "good" },
  { rating: "off", label: "Tone off", icon: "off" },
  { rating: "bad", label: "Bad reply", icon: "bad" },
  { rating: "harmful", label: "Harmful", icon: "harmful" }
];
const dataPointFeedbackReasons = [
  { value: "wrong", label: "Wrong" },
  { value: "not_me", label: "Not me" },
  { value: "too_specific", label: "Too specific" },
  { value: "private", label: "Too private" },
  { value: "not_useful", label: "Not useful" }
];

const routes = {
  interview: document.querySelector("#interview-screen"),
  review: document.querySelector("#review-screen"),
  profile: document.querySelector("#profile-screen"),
  style: document.querySelector("#style-screen"),
  matches: document.querySelector("#matches-screen")
};

const chatLog = document.querySelector("#chat-log");
const chatTitle = document.querySelector("#chat-title");
const chatTitleAvatar = document.querySelector(".terminal-mark img");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const sendMessage = document.querySelector("#send-message");
const agentStatus = document.querySelector("#agent-status");
const agentModelSelect = document.querySelector("#agent-model-select");
const agentNameInput = document.querySelector("#agent-name-input");
const agentToneSelect = document.querySelector("#agent-tone-select");
const agentContextButton = document.querySelector("#agent-context-button");
const agentContextMenu = document.querySelector("#agent-context-menu");
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
const openHistorySheet = document.querySelector("#open-history-sheet");
const closeHistorySheet = document.querySelector("#close-history-sheet");
const chatSidebar = document.querySelector(".chat-sidebar");
const deleteSessionDialog = document.querySelector("#delete-session-dialog");
const deleteSessionId = document.querySelector("#delete-session-id");
const confirmDeleteSession = document.querySelector("#confirm-delete-session");
const cancelDeleteSession = document.querySelector("#cancel-delete-session");
const deleteMemoryDialog = document.querySelector("#delete-memory-dialog");
const deleteMemoryName = document.querySelector("#delete-memory-name");
const confirmDeleteMemory = document.querySelector("#confirm-delete-memory");
const cancelDeleteMemory = document.querySelector("#cancel-delete-memory");
const factEvidenceDialog = document.querySelector("#fact-evidence-dialog");
const factEvidenceTitle = document.querySelector("#fact-evidence-title");
const factEvidenceSummary = document.querySelector("#fact-evidence-summary");
const factEvidenceList = document.querySelector("#fact-evidence-list");
const closeFactEvidence = document.querySelector("#close-fact-evidence");
const sidebarMessageCount = document.querySelector("#sidebar-message-count");
const sidebarConversationId = document.querySelector("#sidebar-conversation-id");
const activeMemoryCount = document.querySelector("#active-memory-count");
const activeMemoryList = document.querySelector("#active-memory-list");
const toneSuggestion = document.querySelector("#tone-suggestion");
const applyDetectedTone = document.querySelector("#apply-detected-tone");
const contextPrompt = document.querySelector("#context-prompt");
const openContextMemory = document.querySelector("#open-context-memory");
const contextMemoryDialog = document.querySelector("#context-memory-dialog");
const closeContextMemory = document.querySelector("#close-context-memory");
const cancelContextMemory = document.querySelector("#cancel-context-memory");
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
const openWhatsappStyle = document.querySelector("#open-whatsapp-style");
const styleImportWhatsapp = document.querySelector("#style-import-whatsapp");
const whatsappStyleDialog = document.querySelector("#whatsapp-style-dialog");
const closeWhatsappStyle = document.querySelector("#close-whatsapp-style");
const cancelWhatsappStyle = document.querySelector("#cancel-whatsapp-style");
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
const appShell = document.querySelector("#app-shell");
const appHeader = document.querySelector(".app-header");
const authScreen = document.querySelector("#auth-screen");
const authScreenLogin = document.querySelector("#auth-screen-login");
const authScreenStatus = document.querySelector("#auth-screen-status");
const datingBasicsScreen = document.querySelector("#dating-basics-screen");
const datingBasicsForm = document.querySelector("#dating-basics-form");
const onboardingStepPanels = Array.from(document.querySelectorAll("[data-onboarding-step]"));
const onboardingStepIndicators = Array.from(document.querySelectorAll("[data-step-indicator]"));
const onboardingBackStep = document.querySelector("#onboarding-back-step");
const onboardingNextStep = document.querySelector("#onboarding-next-step");
const basicsName = document.querySelector("#basics-name");
const profileDob = document.querySelector("#profile-dob");
const profileGender = document.querySelector("#profile-gender");
const profileInterestedIn = document.querySelector("#profile-interested-in");
const basicsOptionButtons = Array.from(document.querySelectorAll("[data-profile-option]"));
const profileState = document.querySelector("#profile-state");
const profileCity = document.querySelector("#profile-city");
const profilePhone = document.querySelector("#profile-phone");
const profilePhoto = document.querySelector("#profile-photo");
const profilePhotoPreview = document.querySelector("#profile-photo-preview");
const profilePhotoPreviews = Array.from(document.querySelectorAll("[data-photo-preview]"));
const profilePhotoTriggers = Array.from(document.querySelectorAll("[data-profile-photo-trigger]"));
const profileForm = document.querySelector("#profile-form");
const profileName = document.querySelector("#profile-name");
const profileEmail = document.querySelector("#profile-email");
const accountAge = document.querySelector("#account-age");
const accountGender = document.querySelector("#account-gender");
const accountInterestedIn = document.querySelector("#account-interested-in");
const accountState = document.querySelector("#account-state");
const accountCity = document.querySelector("#account-city");
const accountPhone = document.querySelector("#account-phone");
const accountPhoto = document.querySelector("#account-photo");
const accountPhotoPreviews = Array.from(document.querySelectorAll("[data-account-photo-preview]"));
const accountPhotoTriggers = Array.from(document.querySelectorAll("[data-account-photo-trigger]"));
const profileStatus = document.querySelector("#profile-status");
const profileFactTotal = document.querySelector("#profile-fact-total");
const profileFactGroups = document.querySelector("#profile-fact-groups");
const rawProfileDataPanel = document.querySelector("#raw-profile-data-panel");
const rawProfileDataTotal = document.querySelector("#raw-profile-data-total");
const rawProfileDataList = document.querySelector("#raw-profile-data-list");
const datingBasicsStatus = document.querySelector("#dating-basics-status");
const saveDatingBasics = document.querySelector("#save-dating-basics");
const loginGoogle = document.querySelector("#login-google");
const logoutUser = document.querySelector("#logout-user");
const authUser = document.querySelector("#auth-user");
const authAvatar = document.querySelector("#auth-avatar");
const authEmail = document.querySelector("#auth-email");
const accountMenu = document.querySelector("#account-menu");
const accountMenuProfile = document.querySelector("#account-menu-profile");
const accountMenuSignout = document.querySelector("#account-menu-signout");
const menuButton = document.querySelector("#menu-button");
const appNav = document.querySelector("#main-navigation");

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
    if (element) {
      element.hidden = key !== name;
    }
  });
  closeMobileHistorySheet();
  closeAppMenu();
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === name);
  });
  if (name === "profile" || name === "style") {
    loadProfilePage();
  }
  if (name === "style") {
    loadContextSources();
  }
  updateAppHeaderHeight();
}

function closeAppMenu() {
  appNav?.classList.remove("is-open");
  menuButton?.setAttribute("aria-expanded", "false");
  updateAppHeaderHeight();
}

function toggleAppMenu() {
  if (!appNav || !menuButton) return;
  const isOpen = appNav.classList.toggle("is-open");
  if (isOpen) closeAccountMenu();
  menuButton.setAttribute("aria-expanded", String(isOpen));
  updateAppHeaderHeight();
}

function updateAppHeaderHeight() {
  if (!appShell || !appHeader) return;
  window.requestAnimationFrame(() => {
    const height = Math.ceil(appHeader.getBoundingClientRect().height);
    appShell.style.setProperty("--app-header-height", `${height}px`);
  });
}

function currentDraftIdFromPath() {
  const match = window.location.pathname.match(/^\/drafts\/([^/]+)$/);
  return match ? match[1] : null;
}

function linkedConversationTargetFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const conversation = params.get("conversation");
  const message = Number(params.get("message"));
  if (!conversation || !Number.isFinite(message) || message < 1) {
    return null;
  }
  return {
    conversationId: conversation,
    messageIndex: message - 1
  };
}

async function initializeAuth() {
  renderSignedOutAuth("Checking...");
  try {
    const response = await fetch("/api/auth/config");
    if (!response.ok) {
      throw new Error("Auth config unavailable.");
    }
    const config = await response.json();
    authProvider = config.auth_provider || (config.supabase_url ? "supabase" : "none");
    const supabaseConfig = config.providers?.supabase || {
      url: config.supabase_url,
      anon_key: config.supabase_anon_key
    };
    authRequired = Boolean(config.auth_gate_required ?? config.auth_required);
    profileDebugDataEnabled = Boolean(config.profile_debug_data_enabled);
    if (authProvider === "none") {
      renderSignedOutAuth("Auth not configured");
      renderAuthGate();
      return;
    }
    if (authProvider !== "supabase") {
      renderSignedOutAuth(`${authProvider} auth is not supported in this client yet`);
      renderAuthGate();
      return;
    }
    if (!supabaseConfig.url || !supabaseConfig.anon_key) {
      renderSignedOutAuth("Auth not configured");
      renderAuthGate();
      return;
    }
    if (!window.supabase?.createClient) {
      throw new Error("Supabase client unavailable.");
    }

    supabaseClient = window.supabase.createClient(
      supabaseConfig.url,
      supabaseConfig.anon_key
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
  const displayName = googleDisplayName(user) || email;
  if (authUser) {
    authUser.hidden = false;
  }
  if (authEmail) {
    authEmail.textContent = displayName;
  }
  renderHeaderAvatar(displayName);
  if (loginGoogle) {
    loginGoogle.hidden = true;
    loginGoogle.disabled = false;
  }
  if (logoutUser) {
    logoutUser.hidden = true;
    logoutUser.disabled = false;
  }
  updateAppHeaderHeight();
  renderAuthGate();
  loadDatingBasicsStatus();
  if (window.location.pathname === "/profile") {
    loadProfilePage();
  }
}

function googleDisplayName(user) {
  const metadata = user?.user_metadata || {};
  return metadata.full_name || metadata.name || metadata.display_name || "";
}

function signedInUserPhotoUrl() {
  const metadata = authSession?.user?.user_metadata || {};
  return metadata.avatar_url || metadata.picture || metadata.photo_url || "";
}

function renderHeaderAvatar(displayName = "") {
  if (!authAvatar) return;

  authAvatar.replaceChildren();
  const photoUrl = accountProfilePhotoUrls.find(Boolean) || signedInUserPhotoUrl();
  if (photoUrl) {
    const image = document.createElement("img");
    image.src = photoUrl;
    image.alt = "";
    authAvatar.appendChild(image);
    return;
  }

  authAvatar.textContent = String(displayName || "U").trim().slice(0, 1).toUpperCase() || "U";
}

function closeAccountMenu() {
  if (accountMenu) accountMenu.hidden = true;
  authUser?.setAttribute("aria-expanded", "false");
}

function toggleAccountMenu() {
  if (!accountMenu || !authUser) return;
  const willOpen = accountMenu.hidden;
  if (willOpen) closeAppMenu();
  accountMenu.hidden = !willOpen;
  authUser.setAttribute("aria-expanded", String(willOpen));
}

function appReturnUrl() {
  const path = window.location.pathname === "/" ? "/app" : window.location.pathname;
  return `${window.location.origin}${path}${window.location.search}${window.location.hash}`;
}

function openProfilePage() {
  window.location.href = "/profile";
}

function renderSignedOutAuth(label) {
  closeAccountMenu();
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
  updateAppHeaderHeight();
  if (authScreenStatus) {
    authScreenStatus.textContent = label || "Sign in to continue.";
  }
}

function renderAuthGate(message) {
  const signedIn = Boolean(authSession?.user);
  const shouldAuthGate = authRequired && !signedIn;
  const shouldBasicsGate = !shouldAuthGate && signedIn && datingBasicsComplete === false;
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
  if (shouldBasicsGate) {
    renderOnboardingStep(onboardingStep);
  }
  if (authScreenLogin) {
    authScreenLogin.disabled = !supabaseClient;
  }
  if (authScreenStatus) {
    authScreenStatus.textContent = message || (signedIn ? "Signed in." : "Sign in to continue.");
  }
}

async function resetToSignIn(message = "Sign in to continue.") {
  datingBasicsComplete = null;
  onboardingStep = 1;
  try {
    await supabaseClient?.auth.signOut();
  } catch {
    // A stale local session should not keep the user trapped behind onboarding.
  }
  authSession = null;
  renderSignedOutAuth("Continue with Google");
  renderAuthGate(message);
}

async function loadDatingBasicsStatus() {
  if (!authSession?.user) return;

  try {
    const response = await apiFetch("/api/me/dating-basics");
    if (response.status === 401) {
      await resetToSignIn("Sign in to continue.");
      return;
    }
    if (!response.ok) {
      throw new Error("Could not load dating basics.");
    }
    const data = await response.json();
    datingBasicsComplete = Boolean(data.complete);
    if (data.profile) {
      if (basicsName) basicsName.value = data.profile.display_name || googleDisplayName(authSession?.user) || "";
      if (profileGender) profileGender.value = data.profile.gender || "";
      if (profileInterestedIn) profileInterestedIn.value = data.profile.interested_in || "";
      await setLocationControls(profileState, profileCity, data.profile.city || "");
      if (profilePhone) profilePhone.value = data.profile.phone || "";
      const profilePhotoUrls = data.profile.profile_photo_urls?.length ? data.profile.profile_photo_urls : [data.profile.profile_photo_url];
      accountProfilePhotoUrls = profilePhotoUrls.filter(Boolean).slice(0, 4);
      renderProfilePhotoGallery(profilePhotoUrls);
      renderHeaderAvatar(data.profile.display_name || googleDisplayName(authSession?.user) || authSession?.user?.email || "");
      syncBasicsOptionButtons();
    }
    renderAuthGate();
    if (!datingBasicsComplete) {
      renderOnboardingStep(1);
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

async function loadIndiaLocations() {
  if (indiaLocations) return indiaLocations;
  const response = await fetch("/static/locations/india_locations.json");
  if (!response.ok) {
    throw new Error("Could not load location list.");
  }
  indiaLocations = await response.json();
  populateStateSelect(profileState);
  populateStateSelect(accountState);
  return indiaLocations;
}

function populateStateSelect(select) {
  if (!select || !indiaLocations) return;
  const currentValue = select.value;
  select.innerHTML = `<option value="">Choose state</option>`;
  (indiaLocations.states || []).forEach((state) => {
    const option = document.createElement("option");
    option.value = state.code;
    option.textContent = state.name;
    select.appendChild(option);
  });
  if (currentValue) {
    select.value = currentValue;
  }
}

function populateCitySelect(stateSelect, citySelect, selectedCity = "") {
  if (!citySelect || !indiaLocations) return;
  const stateCode = stateSelect?.value || "";
  const cities = stateCode ? indiaLocations.citiesByState?.[stateCode] || [] : [];
  citySelect.innerHTML = `<option value="">${stateCode ? "Choose city" : "Choose state first"}</option>`;
  cities.forEach((city) => {
    const option = document.createElement("option");
    option.value = city.name;
    option.textContent = city.name;
    citySelect.appendChild(option);
  });
  citySelect.disabled = !stateCode;
  if (selectedCity) {
    citySelect.value = selectedCity;
  }
}

function stateNameFromCode(stateCode) {
  return (indiaLocations?.states || []).find((state) => state.code === stateCode)?.name || "";
}

function stateCodeFromName(stateName) {
  const normalized = String(stateName || "").trim().toLowerCase();
  return (indiaLocations?.states || []).find((state) => state.name.toLowerCase() === normalized)?.code || "";
}

function parseStoredLocation(value) {
  const parts = String(value || "").split(",").map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) {
    const stateName = parts[parts.length - 1];
    return {
      city: parts.slice(0, -1).join(", "),
      stateCode: stateCodeFromName(stateName)
    };
  }
  return { city: parts[0] || "", stateCode: "" };
}

function composeLocationValue(stateSelect, citySelect) {
  const city = citySelect?.value?.trim() || "";
  const stateName = stateNameFromCode(stateSelect?.value || "");
  return city && stateName ? `${city}, ${stateName}` : city;
}

async function setLocationControls(stateSelect, citySelect, storedLocation = "") {
  await loadIndiaLocations();
  const parsed = parseStoredLocation(storedLocation);
  if (stateSelect) {
    stateSelect.value = parsed.stateCode;
  }
  populateCitySelect(stateSelect, citySelect, parsed.city);
}

function renderOnboardingStep(step = onboardingStep) {
  onboardingStep = 1;
  onboardingStepPanels.forEach((panel) => {
    panel.hidden = Number(panel.dataset.onboardingStep) !== onboardingStep;
  });
  onboardingStepIndicators.forEach((indicator) => {
    const indicatorStep = Number(indicator.dataset.stepIndicator);
    indicator.classList.toggle("active", indicatorStep === onboardingStep);
    indicator.classList.toggle("complete", indicatorStep < onboardingStep);
  });
  if (onboardingBackStep) {
    onboardingBackStep.hidden = onboardingStep === 1;
  }
  if (onboardingNextStep) {
    onboardingNextStep.hidden = true;
  }
  if (saveDatingBasics) {
    saveDatingBasics.hidden = false;
  }
  clearDatingBasicsFieldErrors();
  if (datingBasicsStatus) {
    datingBasicsStatus.textContent = "";
  }
}

function goToNextOnboardingStep() {
  renderOnboardingStep(1);
  basicsName?.focus();
}

function goToPreviousOnboardingStep() {
  renderOnboardingStep(1);
}

function syncBasicsOptionButtons() {
  basicsOptionButtons.forEach((button) => {
    const select = document.querySelector(`#${button.dataset.profileOption}`);
    const isSelected = Boolean(select && select.value === button.dataset.value);
    button.classList.toggle("is-selected", isSelected);
    button.setAttribute("aria-pressed", isSelected ? "true" : "false");
  });
}

function selectBasicsOption(targetId, value, dispatchChange = true) {
  const select = document.querySelector(`#${targetId}`);
  if (!select) return;
  select.value = value;
  if (dispatchChange) {
    select.dispatchEvent(new Event("change", { bubbles: true }));
    syncBasicsOptionButtons();
  } else {
    syncBasicsOptionButtons();
  }
}

function updateInterestedInDefault() {
  if (!profileGender || !profileInterestedIn) return;
  profileInterestedIn.value = defaultInterestedIn(profileGender.value);
  setFieldError(profileInterestedIn, "");
  syncBasicsOptionButtons();
}

function updateAccountInterestedInDefault() {
  if (!accountGender || !accountInterestedIn) return;
  accountInterestedIn.value = defaultInterestedIn(accountGender.value);
}

function formatDateInputValue(date) {
  return date.toISOString().slice(0, 10);
}

function setDobBounds() {
  if (!profileDob) return;
  const today = new Date();
  const maxDob = new Date(today.getFullYear() - 18, today.getMonth(), today.getDate());
  const minDob = new Date(today.getFullYear() - 100, today.getMonth(), today.getDate());
  profileDob.max = formatDateInputValue(maxDob);
  profileDob.min = formatDateInputValue(minDob);
}

function ageFromDob(value) {
  if (!value) return null;
  const dob = new Date(`${value}T00:00:00`);
  if (Number.isNaN(dob.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const hadBirthdayThisYear =
    today.getMonth() > dob.getMonth() ||
    (today.getMonth() === dob.getMonth() && today.getDate() >= dob.getDate());
  if (!hadBirthdayThisYear) {
    age -= 1;
  }
  return age;
}

function setFieldError(field, message = "") {
  const fieldShell = field?.closest?.(".basics-field");
  const errorText = fieldShell?.querySelector?.(".field-error");
  if (!fieldShell || !errorText) return;
  fieldShell.classList.toggle("has-error", Boolean(message));
  errorText.textContent = message;
}

function clearDatingBasicsFieldErrors() {
  [basicsName, profileDob, profileGender, profileInterestedIn, profileState, profileCity, profilePhone].forEach((field) => {
    if (field) setFieldError(field, "");
  });
}

async function saveDatingBasicsProfile(event) {
  event.preventDefault();
  if (!basicsName || !profileDob || !profileGender || !profileInterestedIn || !profileState || !profileCity || !saveDatingBasics) return;

  clearDatingBasicsFieldErrors();
  const ageValue = ageFromDob(profileDob.value);
  const validationChecks = [
    { valid: Boolean(basicsName.value.trim()), message: "Name required", field: basicsName },
    {
      valid: Number.isInteger(ageValue) && ageValue >= 18 && ageValue <= 100,
      message: "18+ required",
      field: profileDob
    },
    { valid: Boolean(profileGender.value), message: "Choose your gender to continue.", field: profileGender },
    { valid: Boolean(profileInterestedIn.value), message: "Choose who you are interested in to continue.", field: profileInterestedIn },
    { valid: Boolean(profileState.value), message: "State required", field: profileState },
    { valid: Boolean(profileCity.value.trim()), message: "City required", field: profileCity }
  ];
  const failedCheck = validationChecks.find((check) => !check.valid);
  if (failedCheck) {
    setFieldError(failedCheck.field, failedCheck.message);
    failedCheck.field?.focus?.();
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
        display_name: basicsName.value.trim(),
        age: ageValue,
        gender: profileGender.value,
        interested_in: profileInterestedIn.value,
        city: composeLocationValue(profileState, profileCity),
        phone: profilePhone?.value.trim() || null
      })
    });
    const data = await response.json();
    if (response.status === 401) {
      await resetToSignIn(data.detail || "Sign in to continue.");
      return;
    }
    if (!response.ok) {
      throw new Error(data.detail || "Could not save dating basics.");
    }
    const photoFiles = onboardingProfilePhotoFiles
      .map((file, slot) => ({ file, slot }))
      .filter((item) => item.file?.type?.startsWith("image/"));
    if (photoFiles.length) {
      let uploaded = null;
      for (const { file, slot } of photoFiles) {
        uploaded = await uploadProfilePhoto(file, slot);
      }
      renderProfilePhotoGallery(uploaded?.profile_photo_urls || [uploaded?.profile_photo_url]);
      onboardingProfilePhotoFiles = Array(4).fill(null);
    }
    datingBasicsComplete = true;
    if (profileName) profileName.value = basicsName.value.trim();
    if (accountAge) accountAge.value = String(ageValue);
    if (accountGender) accountGender.value = profileGender.value;
    if (accountInterestedIn) accountInterestedIn.value = profileInterestedIn.value;
    await setLocationControls(accountState, accountCity, composeLocationValue(profileState, profileCity));
    if (accountPhone) accountPhone.value = profilePhone?.value.trim() || "";
    if (datingBasicsStatus) {
      datingBasicsStatus.textContent = "";
    }
    onboardingStep = 1;
    renderAuthGate();
    showScreen("interview");
    await restoreOrStartConversation();
    focusChatInput();
  } catch (error) {
    if (/location|city/i.test(error.message)) {
      setFieldError(profileCity, "City required");
      profileCity?.focus?.();
    } else if (/age|birth/i.test(error.message)) {
      setFieldError(profileDob, "18+ required");
      profileDob?.focus?.();
    } else if (/name/i.test(error.message)) {
      setFieldError(basicsName, "Name required");
      basicsName?.focus?.();
    } else if (datingBasicsStatus) {
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
    if (accountAge) accountAge.value = profile.age || "";
    if (accountGender) accountGender.value = profile.gender || "prefer_not_to_say";
    if (accountInterestedIn) accountInterestedIn.value = profile.interested_in || "everyone";
    await setLocationControls(accountState, accountCity, profile.city || "");
    if (accountPhone) accountPhone.value = profile.phone || "";
    renderAccountPhotoGallery(profile.profile_photo_urls?.length ? profile.profile_photo_urls : [profile.profile_photo_url]);
    renderContextSources([
      ...(data.memory_sources || []),
      ...(data.style_sources || [])
    ]);
    renderProfileFacts(data.learned_fact_groups || {}, data.learned_facts || []);
    renderRawProfileDataPoints(data.raw_internal_data_points || []);
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
    const ageValue = Number(accountAge?.value);
    if (!profileName?.value.trim() || !Number.isInteger(ageValue) || ageValue < 18 || ageValue > 100 || !accountState?.value || !accountCity?.value.trim()) {
      throw new Error("Name, age, and location are required.");
    }
    const response = await apiFetch("/api/me/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: profileName?.value.trim() || null,
        age: ageValue,
        gender: accountGender.value,
        interested_in: accountInterestedIn.value,
        city: composeLocationValue(accountState, accountCity) || null,
        phone: accountPhone?.value.trim() || null
      })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not save profile.");
    }
    datingBasicsComplete = true;
    if (basicsName) basicsName.value = data.profile.display_name || "";
    if (profileGender) profileGender.value = data.profile.gender || "";
    if (profileInterestedIn) profileInterestedIn.value = data.profile.interested_in || "";
    await setLocationControls(profileState, profileCity, data.profile.city || "");
    if (profilePhone) profilePhone.value = data.profile.phone || "";
    syncBasicsOptionButtons();
    if (profileStatus) {
      profileStatus.textContent = "Profile saved.";
    }
  } catch (error) {
    if (profileStatus) {
      profileStatus.textContent = error.message;
    }
  }
}

async function uploadProfilePhoto(file, slot = null) {
  if (!file) return {};
  if (!file.type || !file.type.startsWith("image/")) {
    throw new Error("Choose an image file for your profile photo.");
  }
  const slotQuery = Number.isInteger(slot) ? `?slot=${slot}` : "";
  const response = await apiFetch(`/api/me/profile-photo${slotQuery}`, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: await file.arrayBuffer()
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Could not upload profile photo.");
  }
  return data;
}

function renderProfilePhotoPreview(preview, url) {
  if (!preview) return;
  const wrapper = preview.closest(".photo-slot, .photo-avatar-shell, .profile-main-photo, .profile-thumb");
  if (!url) {
    preview.hidden = true;
    preview.removeAttribute("src");
    wrapper?.classList.remove("has-photo");
    return;
  }
  preview.src = url;
  preview.hidden = false;
  wrapper?.classList.add("has-photo");
}

function renderProfilePhotoGallery(urls = []) {
  profilePhotoPreviews.forEach((preview, index) => {
    renderProfilePhotoPreview(preview, urls[index] || "");
  });
}

function renderAccountPhotoGallery(urls = []) {
  accountProfilePhotoUrls = urls.slice(0, 4);
  accountPhotoPreviews.forEach((preview, index) => {
    renderProfilePhotoPreview(preview, urls[index] || "");
  });
  renderHeaderAvatar(profileName?.value || googleDisplayName(authSession?.user) || authSession?.user?.email || "");
}

function previewSelectedPhotos() {
  const file = profilePhoto?.files?.[0];
  if (!file) return;
  if (!file.type?.startsWith("image/")) {
    onboardingProfilePhotoFiles[pendingOnboardingPhotoSlot] = null;
    renderProfilePhotoGallery(onboardingProfilePhotoFiles.map((photoFile) => photoFile ? URL.createObjectURL(photoFile) : ""));
    profilePhoto.value = "";
    return;
  }
  onboardingProfilePhotoFiles[pendingOnboardingPhotoSlot] = file;
  const urls = onboardingProfilePhotoFiles.map((photoFile) => photoFile ? URL.createObjectURL(photoFile) : "");
  renderProfilePhotoGallery(urls);
  profilePhoto.value = "";
}

async function uploadSelectedAccountPhoto() {
  const file = accountPhoto?.files?.[0];
  if (!file) return;
  if (!file.type?.startsWith("image/")) {
    if (profileStatus) profileStatus.textContent = "Choose an image file for your profile photo.";
    accountPhoto.value = "";
    return;
  }
  const previewUrls = [...accountProfilePhotoUrls];
  previewUrls[pendingAccountPhotoSlot] = URL.createObjectURL(file);
  accountPhotoPreviews.forEach((preview, index) => {
    renderProfilePhotoPreview(preview, previewUrls[index] || "");
  });
  if (profileStatus) {
    profileStatus.textContent = "Uploading photo...";
  }
  try {
    const uploaded = await uploadProfilePhoto(file, pendingAccountPhotoSlot);
    renderAccountPhotoGallery(uploaded?.profile_photo_urls || [uploaded?.profile_photo_url]);
    if (profileStatus) {
      profileStatus.textContent = "Photo uploaded.";
    }
  } catch (error) {
    renderAccountPhotoGallery(accountProfilePhotoUrls);
    if (profileStatus) {
      profileStatus.textContent = error.message;
    }
  } finally {
    accountPhoto.value = "";
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

function renderProfileFacts(groups, facts) {
  if (!profileFactGroups) return;
  const factList = Array.isArray(facts) ? facts : [];
  profileFactList = factList;
  profileFactGroupsData = groups || {};
  profileFactsById = new Map(factList.map((fact) => [String(fact.id), fact]));
  if (profileFactTotal) {
    profileFactTotal.textContent = `${formatNumber(factList.length)} ${factList.length === 1 ? "fact" : "facts"}`;
  }
  if (!factList.length) {
    profileFactGroups.innerHTML = `
      <div class="profile-facts-empty">
        <strong>No learned signals yet.</strong>
        <span>Chat naturally with Omiryn and this section will fill with internal matching signals.</span>
      </div>
    `;
    return;
  }

  const orderedGroups = Object.entries(groups || {})
    .filter(([, groupFacts]) => Array.isArray(groupFacts) && groupFacts.length)
    .sort(([left], [right]) => profileFactCategoryOrder(left) - profileFactCategoryOrder(right));

  profileFactGroups.innerHTML = orderedGroups
    .map(([category, groupFacts]) => `
      <section class="profile-fact-group">
        <div class="profile-fact-group-heading">
          <h3>${escapeHtml(profileFactCategoryLabel(category))}</h3>
          <span>${formatNumber(groupFacts.length)} ${groupFacts.length === 1 ? "signal" : "signals"}</span>
        </div>
        <div class="profile-fact-list">
          ${groupFacts.map(renderProfileFactCard).join("")}
        </div>
      </section>
    `)
    .join("");
}

function renderProfileFactCard(fact) {
  const evidenceCount = profileFactEvidenceItems(fact).length;
  const confidence = Number(fact.confidence || 0);
  const confidencePercent = Math.round(confidence * 100);
  const evidenceLabel = `${formatNumber(evidenceCount)} ${evidenceCount === 1 ? "evidence" : "evidence"}`;
  return `
    <article class="profile-fact-card">
      <div class="profile-fact-card-top">
        <strong>${escapeHtml(fact.label || profileFactCategoryLabel(fact.key || "Signal"))}</strong>
        <span class="confidence-pill ${confidenceClass(confidence)}">${confidencePercent}%</span>
      </div>
      <div class="profile-fact-meta">
        <span class="fact-tag fact-tag-key">${escapeHtml(profileFactKeyLabel(fact.key))}</span>
        <button
          class="fact-tag fact-evidence-trigger"
          type="button"
          data-fact-id="${escapeHtml(fact.id)}"
          ${evidenceCount ? "" : "disabled"}
        >
          ${escapeHtml(evidenceLabel)}
        </button>
        <span class="fact-tag fact-tag-status">${escapeHtml(profileFactStatusLabel(fact.status))}</span>
      </div>
      ${renderDataPointFeedback(fact)}
    </article>
  `;
}

function renderRawProfileDataPoints(points) {
  if (!rawProfileDataPanel || !rawProfileDataList) return;
  const pointList = profileDebugDataEnabled && Array.isArray(points) ? points : [];
  rawProfileDataPoints = pointList;
  rawProfileDataPanel.hidden = !profileDebugDataEnabled;
  if (!profileDebugDataEnabled) {
    return;
  }

  if (rawProfileDataTotal) {
    rawProfileDataTotal.textContent = `${formatNumber(pointList.length)} ${pointList.length === 1 ? "point" : "points"}`;
  }
  if (!pointList.length) {
    rawProfileDataList.innerHTML = `
      <div class="profile-facts-empty">
        <strong>No raw data points yet.</strong>
        <span>Internal data points will appear here when conversation facts are captured.</span>
      </div>
    `;
    return;
  }

  rawProfileDataList.innerHTML = pointList
    .map((point) => renderRawProfileDataPoint(point))
    .join("");
}

function renderRawProfileDataPoint(point) {
  return `
      <article class="raw-data-item">
        <div class="raw-data-item-main">
          <span>${escapeHtml(profileFactCategoryLabel(point.category))}</span>
          <strong>${escapeHtml(point.key || "unknown")}</strong>
          <code>${escapeHtml(rawDataValue(point.value))}</code>
        </div>
        <div class="raw-data-item-meta">
          <span>${Math.round(Number(point.confidence || 0) * 100)}%</span>
          <span>${escapeHtml(point.status || "active")}</span>
          <span>${formatNumber(point.evidence_count || 0)} ev</span>
          <span>${point.used_for_matching ? "matching" : "ignored"}</span>
        </div>
        ${renderDataPointFeedback(point)}
      </article>
    `;
}

function renderDataPointFeedback(point) {
  const feedback = point.feedback || {};
  const rating = feedback.rating || "";
  return `
    <div class="data-point-feedback-card ${rating ? "has-feedback" : ""}" data-point-id="${escapeHtml(point.id || "")}">
      <div class="data-point-feedback-head">
        <div class="data-point-feedback-actions" aria-label="Data point feedback">
          <button
            class="data-point-feedback-button agree ${rating === "agree" ? "selected" : ""}"
            type="button"
            data-point-feedback="agree"
            data-point-id="${escapeHtml(point.id || "")}"
            aria-label="Mark data point correct"
            title="Correct"
          >
            <span aria-hidden="true">✓</span>
          </button>
          <button
            class="data-point-feedback-button disagree ${rating === "disagree" ? "selected" : ""}"
            type="button"
            data-point-feedback="disagree"
            data-point-id="${escapeHtml(point.id || "")}"
            aria-label="Mark data point wrong"
            title="Wrong"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>
    </div>
  `;
}

function dataPointFeedbackReasonLabel(reasonValue) {
  const reason = dataPointFeedbackReasons.find((item) => item.value === reasonValue);
  return reason?.label || "";
}

function renderDataPointFeedbackForm(point) {
  const feedback = point.feedback || {};
  return `
    <form class="data-point-feedback-form" data-point-feedback-form="${escapeHtml(point.id || "")}">
      <select name="reason" aria-label="Why is this data point wrong?">
        ${dataPointFeedbackReasons
          .map((reason) => `
            <option value="${escapeHtml(reason.value)}" ${feedback.reason === reason.value ? "selected" : ""}>
              ${escapeHtml(reason.label)}
            </option>
          `)
          .join("")}
      </select>
      <input
        name="comment"
        maxlength="1000"
        placeholder="Optional note"
        autocomplete="off"
        value="${escapeHtml(feedback.comment || "")}"
      />
      <button type="submit">Save</button>
    </form>
  `;
}

function openDataPointFeedbackDialog(pointId) {
  const point = findDataPointById(pointId);
  if (!point) return;
  activeDataPointFeedbackId = String(pointId);
  closeDataPointFeedbackDialog(false);
  const dialog = document.createElement("div");
  dialog.className = "data-point-feedback-dialog-backdrop";
  dialog.innerHTML = `
    <section class="data-point-feedback-dialog" role="dialog" aria-modal="true" aria-label="Data point feedback">
      <div class="data-point-feedback-dialog-head">
        <strong>Why is this wrong?</strong>
        <button class="data-point-feedback-close" type="button" data-close-data-point-feedback aria-label="Close">×</button>
      </div>
      <p>${escapeHtml(point.label || point.key || "This data point")}</p>
      ${renderDataPointFeedbackForm(point)}
    </section>
  `;
  document.body.appendChild(dialog);
  dialog.querySelector("[data-close-data-point-feedback]")?.addEventListener("click", () => {
    closeDataPointFeedbackDialog();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      closeDataPointFeedbackDialog();
    }
  });
  dialog
    .querySelector("[data-point-feedback-form]")
    ?.addEventListener("submit", handleRawDataPointFeedbackSubmit);
  dialog.querySelector("input, select, button")?.focus();
}

function closeDataPointFeedbackDialog(clearActive = true) {
  document.querySelector(".data-point-feedback-dialog-backdrop")?.remove();
  if (clearActive) {
    activeDataPointFeedbackId = null;
  }
}

function findDataPointById(pointId) {
  const id = String(pointId);
  return (
    profileFactList.find((point) => String(point.id) === id) ||
    rawProfileDataPoints.find((point) => String(point.id) === id) ||
    null
  );
}

function rawDataValue(value) {
  if (value === null || value === undefined) return "{}";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch (_error) {
    return String(value);
  }
}

function handleRawDataPointFeedbackClick(event) {
  const button = event.target.closest("[data-point-feedback]");
  if (!button) return;
  const pointId = button.dataset.pointId;
  const rating = button.dataset.pointFeedback;
  if (!pointId || !rating) return;
  if (rating === "disagree") {
    openDataPointFeedbackDialog(pointId);
    return;
  }
  closeDataPointFeedbackDialog();
  submitDataPointFeedback(pointId, { rating });
}

function handleRawDataPointFeedbackSubmit(event) {
  const form = event.target.closest("[data-point-feedback-form]");
  if (!form) return;
  event.preventDefault();
  const pointId = form.dataset.pointFeedbackForm;
  if (!pointId) return;
  const formData = new FormData(form);
  submitDataPointFeedback(pointId, {
    rating: "disagree",
    reason: String(formData.get("reason") || ""),
    comment: String(formData.get("comment") || "").trim()
  });
}

async function submitDataPointFeedback(pointId, payload) {
  if (!pointId) return;
  try {
    const response = await apiFetch(`/api/me/profile-facts/${encodeURIComponent(pointId)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(data.detail, "Could not save data point feedback."));
    }
    activeDataPointFeedbackId = null;
    closeDataPointFeedbackDialog(false);
    updateDataPointFeedbackState(pointId, data.feedback || null, data.fact || null);
    renderDataPointFeedbackSurfaces();
    if (profileStatus) {
      profileStatus.textContent = "Data point feedback saved.";
    }
  } catch (error) {
    if (profileStatus) {
      profileStatus.textContent = error.message;
    }
  }
}

function updateDataPointFeedbackState(pointId, feedback, fact = null) {
  const updatePoint = (point) =>
    String(point.id) === String(pointId)
      ? { ...point, ...(fact || {}), feedback }
      : point;
  profileFactList = profileFactList.map(updatePoint);
  profileFactGroupsData = Object.fromEntries(
    Object.entries(profileFactGroupsData || {}).map(([category, facts]) => [
      category,
      Array.isArray(facts) ? facts.map(updatePoint) : facts
    ])
  );
  rawProfileDataPoints = rawProfileDataPoints.map(updatePoint);
}

function renderDataPointFeedbackSurfaces() {
  if (profileFactGroups && profileFactList.length) {
    renderProfileFacts(profileFactGroupsData, profileFactList);
  }
  if (rawProfileDataPanel && !rawProfileDataPanel.hidden) {
    renderRawProfileDataPoints(rawProfileDataPoints);
  }
}

function openFactEvidenceDialog(fact, trigger) {
  if (!factEvidenceDialog || !fact) return;
  lastEvidenceTrigger = trigger || null;
  const evidence = profileFactEvidenceItems(fact);
  const confidence = Math.round(Number(fact.confidence || 0) * 100);

  if (factEvidenceTitle) {
    factEvidenceTitle.textContent = fact.label || "Profile signal evidence";
  }
  if (factEvidenceSummary) {
    factEvidenceSummary.innerHTML = `
      <span>${escapeHtml(profileFactCategoryLabel(fact.category))}</span>
      <span>${confidence}% confidence</span>
      <span>${formatNumber(evidence.length)} ${evidence.length === 1 ? "source" : "sources"}</span>
    `;
  }
  if (factEvidenceList) {
    factEvidenceList.innerHTML = evidence.length
      ? evidence.map((item, index) => renderEvidenceItem(item, index)).join("")
      : `<div class="evidence-empty">No saved quote is attached to this signal yet.</div>`;
  }
  factEvidenceDialog.hidden = false;
  closeFactEvidence?.focus();
}

function renderEvidenceItem(item, index) {
  const quote = evidenceItemText(item);
  const conversationId = String(item?.conversation_id || "");
  const messageIndex = Number.isFinite(Number(item?.message_index))
    ? Number(item.message_index) + 1
    : null;
  const href = conversationId && messageIndex
    ? `/?conversation=${encodeURIComponent(conversationId)}&message=${encodeURIComponent(messageIndex)}`
    : "";
  return `
    <article class="evidence-item">
      <div class="evidence-item-body">
        <span class="evidence-item-index">${index + 1}</span>
        <blockquote>${escapeHtml(quote)}</blockquote>
        <p>
          ${href
            ? `<a class="evidence-chat-link" href="${escapeHtml(href)}">Open chat ${escapeHtml(conversationId.slice(0, 8))} · message ${formatNumber(messageIndex)}</a>`
            : "Chat source unavailable"}
        </p>
      </div>
    </article>
  `;
}

function profileFactEvidenceItems(fact) {
  const evidence = Array.isArray(fact?.evidence) ? fact.evidence : [];
  return evidence.filter((item) => evidenceItemText(item));
}

function evidenceItemText(item) {
  return String(item?.quote || item?.text || "").trim();
}

function closeFactEvidenceDialog() {
  if (factEvidenceDialog) {
    factEvidenceDialog.hidden = true;
  }
  if (lastEvidenceTrigger && document.contains(lastEvidenceTrigger)) {
    lastEvidenceTrigger.focus();
  }
  lastEvidenceTrigger = null;
}

function openContextMemoryDialog() {
  if (!contextMemoryDialog) return;
  contextMemoryDialog.hidden = false;
  loadContextImportPrompt();
  contextTitle?.focus();
}

function closeContextMemoryDialog() {
  if (contextMemoryDialog) {
    contextMemoryDialog.hidden = true;
  }
  openContextMemory?.focus();
}

function openWhatsappStyleDialog() {
  if (!whatsappStyleDialog) return;
  whatsappStyleDialog.hidden = false;
  whatsappSender?.focus();
}

function closeWhatsappStyleDialog() {
  if (whatsappStyleDialog) {
    whatsappStyleDialog.hidden = true;
  }
  openWhatsappStyle?.focus();
}

function profileFactCategoryOrder(category) {
  const order = [
    "dating_intent",
    "values",
    "preferences",
    "dealbreakers",
    "communication",
    "lifestyle",
    "location"
  ];
  const index = order.indexOf(category);
  return index === -1 ? order.length : index;
}

function profileFactCategoryLabel(category) {
  const labels = {
    dating_intent: "Dating intent",
    values: "Values",
    preferences: "Preferences",
    dealbreakers: "Dealbreakers",
    communication: "Communication",
    lifestyle: "Lifestyle",
    location: "Location"
  };
  return labels[category] || titleize(category);
}

function profileFactKeyLabel(key) {
  return titleize(key || "signal");
}

function profileFactStatusLabel(status) {
  const labels = {
    active: "Active",
    user_confirmed: "Confirmed",
    needs_review: "Needs review",
    user_rejected: "Rejected",
    archived: "Archived"
  };
  return labels[status] || titleize(status || "active");
}

function confidenceClass(confidence) {
  if (confidence >= 0.8) return "high";
  if (confidence >= 0.6) return "medium";
  return "low";
}

function titleize(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
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
      redirectTo: appReturnUrl()
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

  if (logoutUser) logoutUser.disabled = true;
  if (accountMenuSignout) accountMenuSignout.disabled = true;
  await supabaseClient.auth.signOut();
  authSession = null;
  closeAccountMenu();
  if (accountMenuSignout) accountMenuSignout.disabled = false;
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

async function startConversation(options = {}) {
  const preserveChatFocus = Boolean(options.preserveChatFocus);
  closeMobileHistorySheet();
  await loadAgentStatus();
  if (!preserveChatFocus) {
    chatInput.disabled = true;
  }
  if (extractProfile) extractProfile.disabled = true;
  const response = await apiFetch("/api/agent/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_model: selectedAgentModel(),
      agent_tone: selectedAgentTone()
    })
  });
  const conversation = await response.json();
  hydrateConversation(conversation);
  return conversation;
}

async function restoreOrStartConversation() {
  await loadAgentStatus();
  const linkedTarget = linkedConversationTargetFromUrl();
  const savedConversationId = linkedTarget?.conversationId || storedConversationId();
  isConversationLoading = true;
  renderMessages();
  if (!savedConversationId) {
    const latestConversation = await latestRestorableConversation();
    if (latestConversation) {
      hydrateConversation(latestConversation);
    } else {
      prepareEmptyConversation();
      await loadConversationHistory();
    }
    isConversationLoading = false;
    renderMessages({ preserveScroll: true });
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
    hydrateConversation(conversation, { highlightMessageIndex: linkedTarget?.messageIndex });
  } catch {
    forgetStoredConversation();
    try {
      await startConversation();
    } catch {
      prepareEmptyConversation();
      await loadConversationHistory();
    }
  } finally {
    isConversationLoading = false;
    renderMessages({ preserveScroll: true });
  }
}

async function latestRestorableConversation() {
  try {
    const conversations = await fetchConversationSummaries();
    if (!conversations.length) return null;
    const preferred = conversations.find(
      (conversation) =>
        conversation.user_message_count > 0 ||
        conversation.context_source_count > 0 ||
        conversation.status === "active"
    ) || conversations[0];
    const response = await apiFetch(`/api/agent/conversations/${preferred.id}`);
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

function prepareEmptyConversation() {
  conversationId = null;
  currentAgentName = null;
  messages = [];
  isConversationLoading = false;
  revealedFeedbackMessageIndex = null;
  messageFeedbackState.clear();
  feedbackLoadedConversationId = null;
  feedbackLoadPromise = null;
  pendingContextSourceIds = [];
  chatInput.disabled = false;
  if (extractProfile) extractProfile.disabled = true;
  renderMessages();
  updateReadiness();
  updateSidebarMeta();
  loadContextImportPrompt();
  renderContextSources([]);
  renderActiveMemory([]);
  renderContextPickerOptions([]);
  focusChatInput();
}

function hydrateConversation(conversation, options = {}) {
  rememberConversation(conversation.id);
  isConversationLoading = false;
  currentAgentName = conversation.agent_name || defaultAgentName();
  messages = conversation.messages;
  revealedFeedbackMessageIndex = null;
  messageFeedbackState.clear();
  feedbackLoadedConversationId = null;
  feedbackLoadPromise = null;
  pendingMessageHighlightIndex = Number.isFinite(Number(options.highlightMessageIndex))
    ? Number(options.highlightMessageIndex)
    : null;
  if (conversation.agent_model && agentModelSelect) {
    agentModelSelect.value = conversation.agent_model;
  }
  if (agentNameInput) {
    agentNameInput.value = currentAgentName;
  }
  if (conversation.agent_tone && agentToneSelect) {
    agentToneSelect.value = conversation.agent_tone;
  }
  pendingContextSourceIds = [];
  updateAgentStatusModel();
  chatInput.disabled = false;
  if (extractProfile) extractProfile.disabled = false;
  renderMessages();
  scrollToHighlightedMessage();
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

function selectedAgentName() {
  if (agentNameInput) {
    return agentNameInput.value.trim();
  }
  return currentAgentName;
}

function stableIndexForText(text, length) {
  if (!length) return 0;
  const value = String(text || "");
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash % length;
}

function agentGenderForName(name) {
  const normalized = String(name || "").trim();
  if (agentNamePools.men.includes(normalized)) return "men";
  if (agentNamePools.women.includes(normalized)) return "women";
  const interestedIn = accountInterestedIn?.value || profileInterestedIn?.value || "";
  if (interestedIn === "men") return "men";
  return "women";
}

function agentAvatarUrl(name = selectedAgentName() || defaultAgentName()) {
  const gender = agentGenderForName(name);
  const assets = agentAvatarAssets[gender] || agentAvatarAssets.women;
  return assets[stableIndexForText(name || gender, assets.length)] || agentAvatarAssets.women[0];
}

function defaultAgentName() {
  const interestedIn = accountInterestedIn?.value || profileInterestedIn?.value || "";
  if (interestedIn === "women") return "Annie";
  if (interestedIn === "men") return "Kabir";
  return "Mira";
}

function conversationAgentName(conversation) {
  return conversation?.agent_name || defaultAgentName();
}

function selectedAgentTone() {
  return agentToneSelect ? agentToneSelect.value : "auto";
}

function updateAgentStatusModel() {
  if (!agentStatus) return;

  const provider = agentStatus.dataset.provider || "Agent";
  const agentName = selectedAgentName() || defaultAgentName();
  if (chatTitle) {
    chatTitle.textContent = agentName;
  }
  if (chatTitleAvatar) {
    chatTitleAvatar.src = agentAvatarUrl(agentName);
  }
  agentStatus.textContent = `${provider} · ${agentToneLabel(selectedAgentTone())} · ${selectedAgentModel() || "no model"}`;
}

async function updateConversationModel() {
  if (!conversationId) return;

  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_model: selectedAgentModel(),
        agent_name: selectedAgentName(),
        agent_tone: selectedAgentTone()
      })
    });
    const conversation = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(conversation.detail, "Could not update agent settings."));
    }
    if (conversation.agent_model && agentModelSelect) {
      agentModelSelect.value = conversation.agent_model;
    }
    currentAgentName = conversation.agent_name || defaultAgentName();
    if (agentNameInput) {
      agentNameInput.value = currentAgentName;
    }
    if (conversation.agent_tone && agentToneSelect) {
      agentToneSelect.value = conversation.agent_tone;
    }
    updateAgentStatusModel();
    renderMessages({ preserveScroll: true });
    loadDetectedTone();
  } catch (error) {
    if (agentStatus) {
      agentStatus.textContent = error.message;
    }
  }
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

function contextSelectionLabel() {
  const count = pendingContextSourceIds.length;
  return count ? `${count} context` : "No context";
}

function titleCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function renderMessages(options = {}) {
  const preserveScroll = Boolean(options.preserveScroll);
  const previousScrollTop = chatLog.scrollTop;
  chatLog.innerHTML = "";
  chatLog.classList.toggle("feedback-open", activeFeedbackMessageIndex !== null);
  if (!messages.length && !isAwaitingAgentReply && !isAssistantTyping) {
    chatLog.appendChild(renderConversationState());
  }
  messages.forEach((message, index) => {
    const isAgent = message.role === "assistant";
    const row = document.createElement("div");
    row.className = `message-row ${isAgent ? "agent" : "user"}`;

    const bubble = document.createElement("div");
    bubble.className = `message ${isAgent ? "agent" : "user"}`;
    bubble.dataset.messageIndex = String(index);
    if (index === pendingMessageHighlightIndex) {
      bubble.classList.add("evidence-highlight");
    }
    if (message.quality === "low_information") {
      bubble.classList.add("low-information");
    }

    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = message.content;
    bubble.appendChild(content);

    if (isAgent) {
      bubble.classList.add("has-feedback");
      if (revealedFeedbackMessageIndex === index) {
        bubble.classList.add("feedback-revealed");
      }
      bubble.addEventListener("click", (event) => {
        if (!isTouchFeedbackMode() || event.target.closest(".message-feedback")) return;
        revealedFeedbackMessageIndex = revealedFeedbackMessageIndex === index ? null : index;
        renderMessages({ preserveScroll: true });
      });
      bubble.appendChild(renderMessageFeedback(index));
    }

    if (isAgent) {
      row.appendChild(renderChatAvatar("agent"));
      row.appendChild(bubble);
    } else {
      row.appendChild(bubble);
      row.appendChild(renderChatAvatar("user"));
    }
    chatLog.appendChild(row);
  });
  if (isAwaitingAgentReply || isAssistantTyping) {
    chatLog.appendChild(renderTypingIndicator());
  }
  chatLog.scrollTop = preserveScroll ? previousScrollTop : chatLog.scrollHeight;
  updateSidebarMeta();
}

function renderConversationState() {
  const state = document.createElement("div");
  state.className = "chat-empty-state";

  const title = document.createElement("strong");
  title.textContent = isConversationLoading ? "Loading conversation..." : "No conversation selected";

  const copy = document.createElement("span");
  copy.textContent = isConversationLoading
    ? "Fetching the latest chat and context."
    : "Choose a conversation from History or start a new chat.";

  state.append(title, copy);
  return state;
}

function renderChatAvatar(role) {
  const avatar = document.createElement("span");
  avatar.className = `chat-avatar ${role}`;
  avatar.setAttribute("aria-hidden", "true");

  if (role === "agent") {
    const image = document.createElement("img");
    image.src = agentAvatarUrl();
    image.alt = "";
    avatar.appendChild(image);
    return avatar;
  }

  const photoUrl = accountProfilePhotoUrls.find(Boolean) || signedInUserPhotoUrl();
  if (photoUrl) {
    const image = document.createElement("img");
    image.src = photoUrl;
    image.alt = "";
    avatar.appendChild(image);
    return avatar;
  }

  const name = profileName?.value || basicsName?.value || googleDisplayName(authSession?.user) || authSession?.user?.email || "U";
  avatar.textContent = name.trim().slice(0, 1).toUpperCase() || "U";
  return avatar;
}

function renderTypingIndicator() {
  const row = document.createElement("div");
  row.className = "message-row agent";

  const bubble = document.createElement("div");
  bubble.className = "message agent typing-message";
  bubble.setAttribute("role", "status");
  bubble.setAttribute("aria-live", "polite");

  const content = document.createElement("div");
  content.className = "message-content typing-content";

  const label = document.createElement("span");
  label.className = "sr-only";
  label.textContent = `${currentAgentName || defaultAgentName()} is typing`;
  content.appendChild(label);

  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 3; index += 1) {
    dots.appendChild(document.createElement("span"));
  }
  content.appendChild(dots);

  bubble.appendChild(content);
  row.appendChild(renderChatAvatar("agent"));
  row.appendChild(bubble);
  return row;
}

function renderMessageFeedback(messageIndex) {
  const state = messageFeedbackState.get(messageIndex) || {};
  const wrapper = document.createElement("div");
  wrapper.className = "message-feedback";
  wrapper.dataset.messageIndex = String(messageIndex);
  if (activeFeedbackMessageIndex === messageIndex) {
    wrapper.classList.add("active");
  }
  if (revealedFeedbackMessageIndex === messageIndex) {
    wrapper.classList.add("revealed");
  }
  if (state.menuPlacement) {
    wrapper.classList.add(`placement-${state.menuPlacement}`);
  }
  if (Number.isFinite(state.menuLeft)) {
    wrapper.style.setProperty("--feedback-popover-left", `${state.menuLeft}px`);
  }
  if (Number.isFinite(state.menuTop)) {
    wrapper.style.setProperty("--feedback-popover-top", `${state.menuTop}px`);
  }

  const actions = document.createElement("div");
  actions.className = "message-feedback-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.className = `message-feedback-trigger ${state.status === "saved" ? "saved" : ""} ${state.status === "loading" ? "loading" : ""}`;
  button.innerHTML = feedbackFlagIcon();
  button.title = state.status === "loading"
    ? "Loading feedback..."
    : state.status === "saved"
      ? "Feedback submitted. Edit feedback"
      : "Give feedback";
  button.setAttribute(
    "aria-label",
    state.status === "loading"
      ? "Loading feedback"
      : state.status === "saved"
        ? "Feedback submitted. Edit feedback"
        : "Give feedback on this reply"
  );
  button.setAttribute("aria-expanded", activeFeedbackMessageIndex === messageIndex ? "true" : "false");
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    handleFeedbackTriggerClick(messageIndex, button);
  });
  actions.appendChild(button);
  wrapper.appendChild(actions);

  if (activeFeedbackMessageIndex === messageIndex) {
    wrapper.appendChild(renderFeedbackPopover(messageIndex, state));
  }

  return wrapper;
}

function feedbackMenuPosition(anchorElement, menuElement = null) {
  const anchor = anchorElement.getBoundingClientRect();
  const chatBounds = feedbackMenuBounds();
  const gap = 10;
  const width = Math.min(menuElement?.offsetWidth || 340, chatBounds.right - chatBounds.left);
  const height = Math.min(menuElement?.offsetHeight || 300, chatBounds.bottom - chatBounds.top);
  const centerX = anchor.left + anchor.width / 2;
  const centerY = anchor.top + anchor.height / 2;

  const candidates = [
    {
      placement: "left",
      left: anchor.left - width - gap,
      top: centerY - height / 2
    },
    {
      placement: "right",
      left: anchor.right + gap,
      top: centerY - height / 2
    },
    {
      placement: "top",
      left: centerX - width / 2,
      top: anchor.top - height - gap
    },
    {
      placement: "bottom",
      left: centerX - width / 2,
      top: anchor.bottom + gap
    }
  ].map((candidate, index) => {
    const overflow = feedbackMenuOverflow(candidate, width, height, chatBounds);
    return {
      ...candidate,
      index,
      overflow,
      score: overflow.total * 100 + index
    };
  });

  const best = candidates.find((candidate) => candidate.overflow.total === 0)
    || candidates.sort((first, second) => first.score - second.score)[0];
  return {
    menuPlacement: best.placement,
    menuLeft: clamp(best.left, chatBounds.left, chatBounds.right - width),
    menuTop: clamp(best.top, chatBounds.top, chatBounds.bottom - height)
  };
}

function syncFeedbackPopoverPosition(messageIndex) {
  const wrapper = chatLog.querySelector(`.message-feedback[data-message-index="${messageIndex}"]`);
  const trigger = wrapper?.querySelector(".message-feedback-trigger");
  const popover = wrapper?.querySelector(".message-feedback-popover");
  if (!wrapper || !trigger || !popover) return;

  const menuPosition = feedbackMenuPosition(trigger, popover);
  const previous = messageFeedbackState.get(messageIndex) || {};
  messageFeedbackState.set(messageIndex, {
    ...previous,
    ...menuPosition
  });
  wrapper.classList.remove("placement-left", "placement-right", "placement-top", "placement-bottom");
  wrapper.classList.add(`placement-${menuPosition.menuPlacement}`);
  wrapper.style.setProperty("--feedback-popover-left", `${menuPosition.menuLeft}px`);
  wrapper.style.setProperty("--feedback-popover-top", `${menuPosition.menuTop}px`);
}

function scheduleFeedbackPopoverPositionSync() {
  if (activeFeedbackMessageIndex === null || feedbackPositionFrame !== null) return;
  feedbackPositionFrame = window.requestAnimationFrame(() => {
    feedbackPositionFrame = null;
    if (activeFeedbackMessageIndex !== null) {
      syncFeedbackPopoverPosition(activeFeedbackMessageIndex);
    }
  });
}

function isTouchFeedbackMode() {
  return window.matchMedia?.("(hover: none), (pointer: coarse)")?.matches || false;
}

function isMobileChatInputMode() {
  return window.matchMedia?.("(max-width: 680px), (pointer: coarse)")?.matches || false;
}

function feedbackMenuBounds() {
  const chatRect = chatLog?.getBoundingClientRect();
  const margin = 12;
  return {
    left: Math.max(chatRect?.left ?? margin, margin),
    right: Math.min(chatRect?.right ?? window.innerWidth - margin, window.innerWidth - margin),
    top: Math.max(chatRect?.top ?? margin, margin),
    bottom: Math.min(chatRect?.bottom ?? window.innerHeight - margin, window.innerHeight - margin)
  };
}

function feedbackMenuOverflow(candidate, width, height, bounds) {
  const left = Math.max(0, bounds.left - candidate.left);
  const right = Math.max(0, candidate.left + width - bounds.right);
  const top = Math.max(0, bounds.top - candidate.top);
  const bottom = Math.max(0, candidate.top + height - bounds.bottom);
  return {
    left,
    right,
    top,
    bottom,
    total: left + right + top + bottom
  };
}

function feedbackFlagIcon() {
  return `
    <svg class="message-feedback-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M5 21V5.8" />
      <path d="M5 5.8c3.6-2.1 6.8 1.9 10.5-.2 1.2-.7 2.3-.8 3.5-.3v9.2c-1.2-.5-2.3-.4-3.5.3-3.7 2.1-6.9-1.9-10.5.2V5.8Z" />
    </svg>
  `;
}

function renderFeedbackPopover(messageIndex, state) {
  const popover = document.createElement("form");
  popover.className = "message-feedback-popover";
  if (state.status === "loading") {
    popover.innerHTML = `
      <span class="message-feedback-title">Loading feedback...</span>
      <div class="message-feedback-loading" aria-hidden="true"><span></span><span></span><span></span></div>
    `;
    return popover;
  }
  if (state.status === "error") {
    popover.innerHTML = `
      <span class="message-feedback-title">Could not load feedback</span>
      <p class="message-feedback-error">Try opening it again.</p>
    `;
    return popover;
  }
  popover.addEventListener("submit", (event) => {
    event.preventDefault();
    const selectedReasons = selectedFeedbackReasons(popover);
    submitMessageFeedback(messageIndex, {
      rating: feedbackRatingFromReasons(selectedReasons),
      reason: selectedReasons[0] || "other",
      reasons: selectedReasons,
      comment: popover.querySelector("[name='comment']")?.value.trim() || ""
    });
  });

  const title = document.createElement("span");
  title.className = "message-feedback-title";
  title.textContent = "Improve this reply";
  popover.appendChild(title);

  const reasonList = document.createElement("div");
  reasonList.className = "message-feedback-reasons";
  const selectedReasons = Array.isArray(state.reasons)
    ? state.reasons
    : [state.reason].filter(Boolean);
  feedbackOptions().forEach((reason) => {
    const label = document.createElement("label");
    label.className = "message-feedback-reason";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "reasons";
    input.value = reason.value;
    if (selectedReasons.includes(reason.value)) {
      input.checked = true;
    }
    label.appendChild(input);
    label.append(document.createTextNode(reason.label));
    reasonList.appendChild(label);
  });
  popover.appendChild(reasonList);

  const input = document.createElement("textarea");
  input.className = "message-feedback-comment";
  input.name = "comment";
  input.placeholder = "Tell us what should improve...";
  input.maxLength = 500;
  input.rows = 3;
  input.value = state.comment || "";
  input.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Escape") {
      closeFeedbackPopover();
    }
  });
  popover.appendChild(input);

  const footer = document.createElement("div");
  footer.className = "message-feedback-footer";

  const cancel = document.createElement("button");
  cancel.className = "message-feedback-cancel";
  cancel.type = "button";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", (event) => {
    event.stopPropagation();
    closeFeedbackPopover();
  });
  footer.appendChild(cancel);

  const submit = document.createElement("button");
  submit.className = "message-feedback-submit";
  submit.type = "submit";
  submit.textContent = "Submit";
  footer.appendChild(submit);
  popover.appendChild(footer);

  return popover;
}

function feedbackOptions() {
  return feedbackReactions.map((reaction) => ({
    value: `rating_${reaction.rating}`,
    label: reaction.label
  }));
}

async function handleFeedbackTriggerClick(messageIndex, button) {
  const menuPosition = feedbackMenuPosition(button);
  const previous = messageFeedbackState.get(messageIndex) || {};
  activeFeedbackMessageIndex = messageIndex;
  revealedFeedbackMessageIndex = messageIndex;
  messageFeedbackState.set(messageIndex, {
    ...previous,
    ...menuPosition,
    status: "loading"
  });
  renderMessages({ preserveScroll: true });
  syncFeedbackPopoverPosition(messageIndex);

  try {
    await loadConversationFeedback();
    openFeedbackEditor(messageIndex, menuPosition);
  } catch {
    const current = messageFeedbackState.get(messageIndex) || {};
    messageFeedbackState.set(messageIndex, {
      ...current,
      ...menuPosition,
      status: "error"
    });
    renderMessages({ preserveScroll: true });
    syncFeedbackPopoverPosition(messageIndex);
  }
}

function openFeedbackEditor(messageIndex, menuPosition = {}) {
  activeFeedbackMessageIndex = messageIndex;
  revealedFeedbackMessageIndex = messageIndex;
  const previous = messageFeedbackState.get(messageIndex) || {};
  messageFeedbackState.set(messageIndex, {
    rating: previous.rating || "good",
    reason: previous.reason,
    reasons: previous.reasons,
    comment: previous.comment,
    menuPlacement: menuPosition.menuPlacement || previous.menuPlacement,
    menuLeft: Number.isFinite(menuPosition.menuLeft) ? menuPosition.menuLeft : previous.menuLeft,
    menuTop: Number.isFinite(menuPosition.menuTop) ? menuPosition.menuTop : previous.menuTop,
    status: "editing"
  });
  renderMessages({ preserveScroll: true });
  syncFeedbackPopoverPosition(messageIndex);
}

async function loadConversationFeedback(options = {}) {
  if (!conversationId) return;
  const force = Boolean(options.force);
  if (!force && feedbackLoadedConversationId === conversationId) return;
  if (feedbackLoadPromise) return feedbackLoadPromise;

  const loadingConversationId = conversationId;
  feedbackLoadPromise = (async () => {
    const response = await apiFetch(`/api/agent/conversations/${loadingConversationId}/feedback`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(data.detail, "Could not load feedback."));
    }
    if (conversationId !== loadingConversationId) return;
    applyConversationFeedback(data.feedback || []);
    feedbackLoadedConversationId = loadingConversationId;
  })();

  try {
    await feedbackLoadPromise;
  } finally {
    feedbackLoadPromise = null;
  }
}

function applyConversationFeedback(feedbackItems) {
  if (!Array.isArray(feedbackItems)) return;
  feedbackItems.forEach((item) => {
    const messageIndex = Number(item.message_index);
    if (!Number.isInteger(messageIndex)) return;
    const previous = messageFeedbackState.get(messageIndex) || {};
    if (previous.status === "saved" || previous.status === "editing" || previous.status === "saving") return;
    messageFeedbackState.set(messageIndex, {
      ...previous,
      ...feedbackStateFromItem(item)
    });
  });
}

function feedbackStateFromItem(item) {
  const metadata = item.metadata || {};
  const reasons = Array.isArray(metadata.reasons)
    ? metadata.reasons
    : Array.isArray(item.reasons)
      ? item.reasons
      : [item.reason].filter(Boolean);
  return {
    rating: item.rating || feedbackRatingFromReasons(reasons),
    reason: item.reason || reasons[0] || null,
    reasons,
    comment: item.comment || null,
    status: "saved"
  };
}

function selectedFeedbackReasons(form) {
  return Array.from(form.querySelectorAll("[name='reasons']:checked"))
    .map((input) => input.value)
    .filter(Boolean);
}

function feedbackRatingFromReasons(reasons) {
  if (reasons.includes("rating_harmful")) return "harmful";
  if (reasons.includes("rating_bad")) return "bad";
  if (reasons.includes("rating_off")) return "off";
  return "good";
}

function closeFeedbackPopover() {
  if (activeFeedbackMessageIndex === null) return;
  activeFeedbackMessageIndex = null;
  renderMessages({ preserveScroll: true });
}

async function submitMessageFeedback(messageIndex, payload) {
  if (!conversationId) return;
  messageFeedbackState.set(messageIndex, {
    rating: payload.rating,
    reason: payload.reason || null,
    reasons: payload.reasons || [],
    comment: payload.comment || null,
    status: "saving"
  });
  activeFeedbackMessageIndex = null;
  renderMessages({ preserveScroll: true });

  try {
    const response = await apiFetch(
      `/api/agent/conversations/${conversationId}/messages/${messageIndex}/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(data.detail, "Could not save feedback."));
    }
    messageFeedbackState.set(messageIndex, {
      rating: data.feedback?.rating || payload.rating,
      reason: data.feedback?.reason || payload.reason || null,
      reasons: data.feedback?.metadata?.reasons || payload.reasons || [],
      comment: data.feedback?.comment || payload.comment || null,
      status: "saved"
    });
  } catch {
    messageFeedbackState.set(messageIndex, { rating: payload.rating, status: "error" });
  }
  renderMessages({ preserveScroll: true });
}

function scrollToHighlightedMessage() {
  if (!chatLog || pendingMessageHighlightIndex === null) return;
  const target = chatLog.querySelector(`[data-message-index="${pendingMessageHighlightIndex}"]`);
  if (!target) return;
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  pendingMessageHighlightIndex = null;
}

function updateSidebarMeta() {
  if (sidebarMessageCount) {
    const userMessages = messages.filter((message) => message.role === "user").length;
    const totalMessages = messages.length;
    sidebarMessageCount.textContent = `${totalMessages} messages · ${userMessages} user`;
  }

  if (sidebarConversationId) {
    sidebarConversationId.textContent = conversationId
      ? `Conversation ${conversationId.slice(0, 8)}`
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

function openMobileHistorySheet() {
  if (!chatSidebar || !appShell) return;
  showSidePanel("history");
  appShell.classList.add("history-sheet-open");
  chatSidebar.classList.add("is-open");
  closeHistorySheet?.focus();
}

function closeMobileHistorySheet() {
  appShell?.classList.remove("history-sheet-open");
  chatSidebar?.classList.remove("is-open");
}

async function loadConversationHistory() {
  if (!historyList) return;

  try {
    const conversations = await fetchConversationSummaries();
    renderConversationHistory(conversations);
  } catch (error) {
    historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function fetchConversationSummaries() {
  const response = await apiFetch("/api/agent/conversations");
  if (!response.ok) {
    throw new Error("Could not load chat history.");
  }
  const data = await response.json();
  return data.conversations || [];
}

function renderConversationHistory(conversations) {
  if (!historyList) return;

  if (!conversations.length) {
    historyList.innerHTML = '<div class="history-empty">No saved conversations yet.</div>';
    return;
  }

  historyList.innerHTML = "";
  conversations.forEach((conversation) => {
    const title = conversationAgentName(conversation);
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
        <div class="history-title-row">
          <strong class="history-agent-name" title="Double click to rename">${escapeHtml(title)}</strong>
        </div>
        <span>${formatNumber(conversation.message_count || 0)} messages · ${formatNumber(conversation.context_source_count || 0)} signals</span>
        <small>${escapeHtml(updatedAt)}</small>
      </div>
      <button class="history-delete" type="button" aria-label="Delete conversation ${escapeHtml(title)}" title="Delete conversation">
        <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
          <path d="M9 3h6l1 2h4v2H4V5h4l1-2Z"></path>
          <path d="M6 9h12l-.8 11H6.8L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z"></path>
        </svg>
      </button>
    `;
    item.addEventListener("click", () => {
      loadConversation(conversation.id)
        .then(closeMobileHistorySheet)
        .catch((error) => {
          historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
        });
    });
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      loadConversation(conversation.id)
        .then(closeMobileHistorySheet)
        .catch((error) => {
          historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
        });
    });
    item.querySelector(".history-agent-name")?.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      startInlineConversationRename(conversation, event.currentTarget);
    });
    item.querySelector(".history-delete")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openDeleteSessionDialog(conversation.id, event.currentTarget, title);
    });
    historyList.appendChild(item);
  });
}

function startInlineConversationRename(conversation, target) {
  const currentName = conversationAgentName(conversation);
  const input = document.createElement("input");
  input.className = "history-name-input";
  input.type = "text";
  input.maxLength = 40;
  input.value = currentName;
  input.setAttribute("aria-label", "Companion name");

  let finished = false;
  const finish = async (shouldSave) => {
    if (finished) return;
    finished = true;
    const nextName = input.value.trim();
    if (!shouldSave || !nextName) {
      target.textContent = currentName;
      input.replaceWith(target);
      return;
    }
    try {
      await renameConversationFromHistory(conversation, nextName);
    } catch (error) {
      historyList.innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
    }
  };

  target.replaceWith(input);
  input.focus();
  input.select();
  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    }
    if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
}

async function renameConversationFromHistory(conversation, agentName) {
  const currentName = conversationAgentName(conversation);
  if (!agentName || agentName === currentName) {
    await loadConversationHistory();
    return;
  }

  const response = await apiFetch(`/api/agent/conversations/${conversation.id}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_name: agentName })
  });
  const updatedConversation = await response.json();
  if (!response.ok) {
    throw new Error(apiErrorMessage(updatedConversation.detail, "Could not rename companion."));
  }
  if (conversation.id === conversationId) {
    hydrateConversation(updatedConversation);
  } else {
    await loadConversationHistory();
  }
}

function openDeleteSessionDialog(id, trigger, title) {
  if (!id) return;

  pendingDeleteConversationId = id;
  lastDeleteTrigger = trigger || null;
  if (deleteSessionId) {
    deleteSessionId.textContent = title || "this chat";
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

function openDeleteMemoryDialog(sourceId, sourceTitle, trigger) {
  if (!sourceId) return;
  pendingDeleteContextSource = { id: sourceId, title: sourceTitle || "this memory" };
  lastDeleteMemoryTrigger = trigger || null;
  if (deleteMemoryName) {
    deleteMemoryName.textContent = pendingDeleteContextSource.title;
  }
  if (deleteMemoryDialog) {
    deleteMemoryDialog.hidden = false;
  }
  confirmDeleteMemory?.focus();
}

function closeDeleteMemoryDialog() {
  if (deleteMemoryDialog) {
    deleteMemoryDialog.hidden = true;
  }
  pendingDeleteContextSource = null;
  if (lastDeleteMemoryTrigger && document.contains(lastDeleteMemoryTrigger)) {
    lastDeleteMemoryTrigger.focus();
  }
  lastDeleteMemoryTrigger = null;
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
  if (!id) return;
  if (id === conversationId) {
    renderMessages();
    return;
  }

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
    await loadReusableContextSources();
    renderActiveMemory([]);
    renderContextPickerOptions([]);
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
    renderContextSources(data.available_sources || data.sources || []);
    renderActiveMemory(data.sources || []);
    renderContextPickerOptions(data.available_sources || data.sources || []);
    loadDetectedTone();
  } catch (error) {
    setContextStatus(error.message);
  }
}

async function loadReusableContextSources() {
  try {
    const response = await apiFetch("/api/me/profile");
    if (!response.ok) {
      throw new Error("Could not load saved memories.");
    }
    const data = await response.json();
    renderContextSources([
      ...(data.memory_sources || []),
      ...(data.style_sources || [])
    ]);
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
    closeContextMemoryDialog();
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
    if (whatsappSender) {
      whatsappSender.value = "";
    }
    if (whatsappStyleName) {
      whatsappStyleName.value = "";
    }
    if (whatsappContent) {
      whatsappContent.value = "";
    }
    await loadContextSources();
    closeWhatsappStyleDialog();
    setWhatsappStatus(
      `${imports.length} text style${imports.length === 1 ? "" : "s"} imported.`,
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
    contextSourceList.innerHTML = '<div class="context-source-empty">No saved memory yet.</div>';
    setContextStatus("No imported context yet.");
    return;
  }

  contextSourceList.innerHTML = sources
    .map((source) => `
      <div class="context-source-item">
        <div class="context-source-copy">
          <strong>${escapeHtml(source.title)}</strong>
          <span>${escapeHtml(contextSourceLabel(source.source_type))} · ${formatNumber(source.content_length)} chars${source.attached ? " · attached here" : ""}</span>
        </div>
        <button
          class="context-source-delete"
          type="button"
          data-source-id="${escapeHtml(source.id)}"
          data-source-title="${escapeHtml(source.title)}"
          aria-label="Delete ${escapeHtml(source.title)}"
          title="Delete memory"
        >
          ×
        </button>
      </div>
    `)
    .join("");
  contextSourceList.querySelectorAll(".context-source-delete").forEach((button) => {
    button.addEventListener("click", () => {
      openDeleteMemoryDialog(button.dataset.sourceId, button.dataset.sourceTitle, button);
    });
  });
  setContextStatus(`${sources.length} uploaded context item${sources.length === 1 ? "" : "s"}.`);
}

async function deleteContextSource(sourceId) {
  if (!sourceId) return;
  try {
    setContextStatus("Deleting memory...", "working");
    const deleteUrl = conversationId
      ? `/api/agent/conversations/${conversationId}/context-sources/${sourceId}`
      : `/api/me/context-sources/${sourceId}`;
    const response = await apiFetch(deleteUrl, {
      method: "DELETE"
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(data.detail, "Could not delete memory."));
    }
    pendingContextSourceIds = pendingContextSourceIds.filter((id) => id !== sourceId);
    await loadContextSources();
    await loadDetectedTone();
    updateAgentStatusModel();
    setContextStatus("Memory deleted.", "success");
  } catch (error) {
    setContextStatus(error.message, "error");
  }
}

async function confirmDeleteContextSource() {
  const sourceId = pendingDeleteContextSource?.id;
  if (!sourceId) return;
  confirmDeleteMemory.disabled = true;
  cancelDeleteMemory.disabled = true;
  await deleteContextSource(sourceId);
  confirmDeleteMemory.disabled = false;
  cancelDeleteMemory.disabled = false;
  closeDeleteMemoryDialog();
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

function renderContextPickerOptions(sources = []) {
  if (!agentContextButton || !agentContextMenu) return;

  if (!sources.length) {
    pendingContextSourceIds = [];
    agentContextButton.textContent = "No context";
    agentContextMenu.innerHTML = '<div class="context-picker-empty">No uploaded context yet.</div>';
    updateAgentStatusModel();
    return;
  }

  pendingContextSourceIds = sources.filter((source) => source.attached).map((source) => source.id);
  agentContextButton.textContent = pendingContextSourceIds.length
    ? `${pendingContextSourceIds.length} selected`
    : "No context";
  agentContextMenu.innerHTML = sources
    .map((source) => `
      <label class="context-picker-option">
        <input type="checkbox" value="${escapeHtml(source.id)}" ${source.attached ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(source.title)}</strong>
          <small>${escapeHtml(contextSourceLabel(source.source_type))} · ${formatNumber(source.content_length)} chars</small>
        </span>
      </label>
    `)
    .join("");
  agentContextMenu.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.addEventListener("change", syncContextAttachments);
  });
  updateAgentStatusModel();
}

function selectedContextSourceIds() {
  if (!agentContextMenu) return [];
  return Array.from(agentContextMenu.querySelectorAll('input[type="checkbox"]:checked'))
    .map((checkbox) => checkbox.value)
    .filter(Boolean);
}

async function syncContextAttachments() {
  if (!conversationId) return;
  const selectedIds = selectedContextSourceIds();
  pendingContextSourceIds = selectedIds;
  if (agentContextButton) {
    agentContextButton.textContent = selectedIds.length ? `${selectedIds.length} selected` : "No context";
  }
  updateAgentStatusModel();

  try {
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/context-sources/attachments`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_ids: selectedIds })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not update chat context.");
    }
    renderContextSources(data.available_sources || data.sources || []);
    renderActiveMemory(data.sources || []);
    renderContextPickerOptions(data.available_sources || []);
    loadDetectedTone();
  } catch (error) {
    setContextStatus(error.message);
  }
}

function toggleContextPicker() {
  if (!agentContextButton || !agentContextMenu) return;
  const willOpen = agentContextMenu.hidden;
  agentContextMenu.hidden = !willOpen;
  agentContextButton.setAttribute("aria-expanded", String(willOpen));
}

function closeContextPicker() {
  if (!agentContextButton || !agentContextMenu) return;
  agentContextMenu.hidden = true;
  agentContextButton.setAttribute("aria-expanded", "false");
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
      (source) => {
        const selectedSender = source.metadata?.selected_sender || "";
        const inferred = source.metadata?.selected_sender_inferred ? " inferred" : "";
        const senderText = selectedSender ? ` · learned ${selectedSender}${inferred}` : "";
        const truncatedText = source.metadata?.truncated
          ? ` · latest ${formatNumber(source.metadata.imported_char_count || source.content_length || 0)} of ${formatNumber(source.metadata.original_char_count || 0)} chars imported`
          : "";
        return `
          <div class="whatsapp-import-item">
            <strong>${escapeHtml(source.title || "WhatsApp style")}</strong>
            <span>Saved${escapeHtml(senderText)}${escapeHtml(truncatedText)} · ${formatNumber(source.content_length || 0)} chars summary</span>
          </div>
        `;
      }
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

async function playConversationReply(nextMessages, options = {}) {
  if (!Array.isArray(nextMessages) || nextMessages.length <= messages.length) {
    messages = Array.isArray(nextMessages) ? nextMessages : messages;
    return;
  }

  const existingCount = messages.length;
  const pendingMessages = nextMessages.slice(existingCount);
  const timing = replyPlaybackTiming(options);
  messages = nextMessages.slice(0, existingCount);
  let assistantMessageCount = 0;
  for (let index = 0; index < pendingMessages.length; index += 1) {
    const pendingMessage = pendingMessages[index];
    if (pendingMessage.role === "assistant") {
      assistantMessageCount += 1;
      isAssistantTyping = true;
      renderMessages();
      await wait(assistantMessageDelayMs(pendingMessage, assistantMessageCount, timing));
      isAssistantTyping = false;
    }
    messages.push(pendingMessage);
    renderMessages();
  }
  messages = nextMessages;
}

function replyPlaybackTiming(options = {}) {
  const userText = options.userText || latestUserMessageContent();
  const modelWaitMs = Math.max(0, Number(options.modelWaitMs) || 0);
  return {
    modelWaitMs,
    thinkingMs: humanThinkingDelayMs(userText),
    profile: typingProfileForAgent()
  };
}

function assistantMessageDelayMs(message, assistantMessageCount, timing) {
  const typingMs = humanTypingDelayMs(message?.content || "", timing.profile);
  if (assistantMessageCount === 1) {
    return clamp(timing.thinkingMs + typingMs - timing.modelWaitMs, 0, maxThinkingDelayMs + maxTypingDelayMs);
  }
  return typingMs;
}

function humanThinkingDelayMs(userText) {
  const words = wordCount(userText);
  const questionBonus = /[?？]|\b(why|how|kaise|kya|kidhar|kab|should|can|tell|bata)\b/i.test(userText || "") ? 450 : 0;
  return clamp(minThinkingDelayMs + words * 95 + questionBonus, minThinkingDelayMs, maxThinkingDelayMs);
}

function humanTypingDelayMs(text, profile) {
  const words = Math.max(1, wordCount(text));
  const wpm = Math.max(20, Number(profile?.wpm) || typingSpeedProfiles.neutral.wpm);
  const literalTypingMs = (words / wpm) * 60000;
  return clamp(literalTypingMs * typingTimeScale, minTypingDelayMs, maxTypingDelayMs);
}

function typingProfileForAgent() {
  if (Number.isFinite(userTypingProfile.wpm)) {
    return { wpm: clamp(userTypingProfile.wpm * 0.96, 24, 54) };
  }
  const name = String(currentAgentName || defaultAgentName()).trim();
  if (agentNamePools.women.includes(name)) return typingSpeedProfiles.feminine;
  if (agentNamePools.men.includes(name)) return typingSpeedProfiles.masculine;
  return typingSpeedProfiles.neutral;
}

function trackUserTypingInput() {
  autoSizeChatInput();
  const length = chatInput.value.length;
  if (length <= 0) {
    resetUserTypingDraft();
    return;
  }
  if (!userTypingProfile.draftStartedAt || length < userTypingProfile.lastInputLength) {
    userTypingProfile.draftStartedAt = performance.now();
  }
  userTypingProfile.lastInputLength = length;
}

function finalizeUserTypingSample(text) {
  const startedAt = userTypingProfile.draftStartedAt;
  resetUserTypingDraft();
  if (!startedAt || !text) return;

  const durationMinutes = (performance.now() - startedAt) / 60000;
  const words = wordCount(text);
  if (durationMinutes <= 0 || words < 2) return;

  const sampleWpm = clamp(words / durationMinutes, 16, 80);
  const previousWpm = Number.isFinite(userTypingProfile.wpm) ? userTypingProfile.wpm : sampleWpm;
  const sampleWeight = userTypingProfile.samples === 0 ? 1 : 0.28;
  userTypingProfile.wpm = previousWpm * (1 - sampleWeight) + sampleWpm * sampleWeight;
  userTypingProfile.samples = Math.min(userTypingProfile.samples + 1, 20);
}

function resetUserTypingDraft() {
  userTypingProfile.draftStartedAt = null;
  userTypingProfile.lastInputLength = 0;
}

function autoSizeChatInput() {
  if (!chatInput || chatInput.tagName !== "TEXTAREA") return;
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 140)}px`;
}

function latestUserMessageContent() {
  const latest = [...messages].reverse().find((message) => message.role === "user");
  return latest?.content || "";
}

function wordCount(text) {
  const matches = String(text || "").trim().match(/\S+/g);
  return matches ? matches.length : 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function wait(durationMs) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, durationMs);
  });
}

async function sendUserMessage() {
  if (isSendingMessage) return;

  const text = chatInput.value.trim();
  if (!text) return;

  finalizeUserTypingSample(text);
  messages.push({ role: "user", content: text });
  chatInput.value = "";
  autoSizeChatInput();
  isSendingMessage = true;
  isAwaitingAgentReply = true;
  isAssistantTyping = false;
  renderMessages();
  updateReadiness();
  focusChatInput();

  try {
    if (!conversationId) {
      const conversation = await startConversation({ preserveChatFocus: true });
      messages = [...(conversation.messages || []), { role: "user", content: text }];
      renderMessages();
      updateReadiness();
    }
    const modelRequestStartedAt = performance.now();
    const response = await apiFetch(`/api/agent/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });
    const modelWaitMs = performance.now() - modelRequestStartedAt;
    const conversation = await response.json();

    if (!response.ok) {
      throw new Error(conversation.detail || "The agent could not reply.");
    }

    isAwaitingAgentReply = false;
    await playConversationReply(conversation.messages || messages, {
      modelWaitMs,
      userText: text
    });
  } catch (error) {
    isAwaitingAgentReply = false;
    isAssistantTyping = false;
    messages.push({
      role: "assistant",
      content: `I could not answer that yet. ${error.message}`
    });
  } finally {
    isSendingMessage = false;
    isAwaitingAgentReply = false;
    isAssistantTyping = false;
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
    const averageUsage = averageChatUsage(events, summary);
    usageSummary.innerHTML = `
      <div class="sidebar-usage-total">
        <strong>${formatNumber(summary.total_tokens || 0)}</strong>
        <span>total tokens</span>
      </div>
      <div class="sidebar-usage-total">
        <strong>${formatNumber(averageUsage.prompt)}</strong>
        <span>avg input / msg</span>
      </div>
      <div class="sidebar-usage-total">
        <strong>${formatNumber(averageUsage.completion)}</strong>
        <span>avg output / msg</span>
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
            <strong>#${events.length - index} ${escapeHtml(usageRequestKindLabel(event.request_kind))}</strong>
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
  window.location.href = "/profile";
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
    renderUsageSummary(data.summary || {}, data.events || []);
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

function renderUsageSummary(summary, events = []) {
  const averageUsage = averageChatUsage(events, summary);
  usageRequests.textContent = formatNumber(summary.request_count || 0);
  usageRequestDetail.textContent = `${formatNumber(summary.successful_request_count || 0)} successful`;
  usageTotalTokens.textContent = formatNumber(summary.total_tokens || 0);
  usageTokenDetail.textContent = `${formatNumber(summary.prompt_tokens || 0)} input / ${formatNumber(summary.completion_tokens || 0)} output`;
  if (usageAverageInputTokens) {
    usageAverageInputTokens.textContent = formatNumber(averageUsage.prompt);
  }
  if (usageAverageOutputTokens) {
    usageAverageOutputTokens.textContent = formatNumber(averageUsage.completion);
  }
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
    usageEvents.innerHTML = '<tr><td class="table-empty" colspan="7">No agent calls logged yet.</td></tr>';
    return;
  }

  usageEvents.innerHTML = events
    .slice(0, usageTableRowLimit)
    .map((event) => {
      const statusClass = event.success ? "success" : "failed";
      const statusText = event.success ? "Success" : "Failed";
      const cost = event.estimated_cost_usd ? formatUsd(event.estimated_cost_usd) : "-";
      const createdAt = event.created_at ? new Date(event.created_at).toLocaleString() : "";
      const promptDebug = event.raw_usage?.prompt_debug || {};
      const promptSize = promptDebug.total_chars
        ? `${formatNumber(promptDebug.rough_tokens || Math.round(promptDebug.total_chars / 4))} rough`
        : "-";
      const promptSizeDetail = promptDebug.total_chars
        ? `${formatNumber(promptDebug.total_chars)} chars`
        : "";
      return `
        <tr>
          <td>${escapeHtml(usageRequestKindLabel(event.request_kind))}<small>${escapeHtml(createdAt)}</small></td>
          <td>${escapeHtml(event.provider || "-")}<small>${escapeHtml(event.model || "-")}</small></td>
          <td class="mono">${formatNumber(event.total_tokens || 0)}<small>${formatNumber(event.prompt_tokens || 0)} in / ${formatNumber(event.completion_tokens || 0)} out</small></td>
          <td class="mono">${escapeHtml(promptSize)}<small>${escapeHtml(promptSizeDetail)}</small></td>
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

function usageRequestKindLabel(kind) {
  const labels = {
    chat_reply: "Chat reply",
    input_guardrail: "Input guardrail",
    profile_extract: "Profile draft extraction",
    profile_extract_repair: "Profile extraction repair",
    data_point_extract: "Data point extraction",
    profile_signal_extract: "Profile signal extraction",
    profile_signal_backfill: "Profile signal backfill",
    profile_fact_aggregate: "Profile fact aggregation",
    match_snapshot_generate: "Match snapshot generation"
  };
  if (!kind) return "Agent call";
  return labels[kind] || titleize(String(kind).replaceAll("_", " "));
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
  if (event.shiftKey || event.isComposing || isMobileChatInputMode()) return;

  event.preventDefault();
  event.stopPropagation();
  sendUserMessage();
});
chatInput.addEventListener("input", trackUserTypingInput);
sendMessage.addEventListener("pointerdown", (event) => {
  event.preventDefault();
});
sendMessage.addEventListener("click", () => {
  sendUserMessage();
});
resetChat?.addEventListener("click", startConversation);
sidebarResetChat?.addEventListener("click", startConversation);
openHistorySheet?.addEventListener("click", openMobileHistorySheet);
closeHistorySheet?.addEventListener("click", closeMobileHistorySheet);
extractProfile?.addEventListener("click", extractConversationDraft);
saveDraft.addEventListener("click", saveDraftEdits);
approveDraft.addEventListener("click", approveCurrentDraft);
deleteDraft.addEventListener("click", deleteCurrentDraft);
refreshMatches?.addEventListener("click", loadMatches);
refreshUsage?.addEventListener("click", loadUsageDashboard);
sideTabButtons.forEach((button) => {
  button.addEventListener("click", () => showSidePanel(button.dataset.sideTab));
});
agentModelSelect.addEventListener("change", updateConversationModel);
agentNameInput?.addEventListener("change", updateConversationModel);
agentNameInput?.addEventListener("input", updateAgentStatusModel);
agentToneSelect?.addEventListener("change", updateConversationModel);
agentContextButton?.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleContextPicker();
});
applyDetectedTone?.addEventListener("click", applyDetectedToneSelection);
openContextMemory?.addEventListener("click", openContextMemoryDialog);
closeContextMemory?.addEventListener("click", closeContextMemoryDialog);
cancelContextMemory?.addEventListener("click", closeContextMemoryDialog);
openWhatsappStyle?.addEventListener("click", openWhatsappStyleDialog);
styleImportWhatsapp?.addEventListener("click", openWhatsappStyleDialog);
closeWhatsappStyle?.addEventListener("click", closeWhatsappStyleDialog);
cancelWhatsappStyle?.addEventListener("click", closeWhatsappStyleDialog);
copyContextPrompt?.addEventListener("click", copyContextImportPrompt);
saveContextSource?.addEventListener("click", saveConversationContextSource);
saveWhatsappImport?.addEventListener("click", saveWhatsappStyleImport);
whatsappFiles?.addEventListener("change", updateWhatsappFileSelectionStatus);
confirmDeleteSession?.addEventListener("click", confirmDeleteConversation);
cancelDeleteSession?.addEventListener("click", closeDeleteSessionDialog);
confirmDeleteMemory?.addEventListener("click", confirmDeleteContextSource);
cancelDeleteMemory?.addEventListener("click", closeDeleteMemoryDialog);
closeFactEvidence?.addEventListener("click", closeFactEvidenceDialog);
profileFactGroups?.addEventListener("click", (event) => {
  if (event.target.closest("[data-point-feedback]")) {
    handleRawDataPointFeedbackClick(event);
    return;
  }
  const trigger = event.target.closest(".fact-evidence-trigger");
  if (!trigger) return;
  const fact = profileFactsById.get(String(trigger.dataset.factId));
  openFactEvidenceDialog(fact, trigger);
});
profileFactGroups?.addEventListener("submit", handleRawDataPointFeedbackSubmit);
rawProfileDataList?.addEventListener("click", handleRawDataPointFeedbackClick);
rawProfileDataList?.addEventListener("submit", handleRawDataPointFeedbackSubmit);
factEvidenceDialog?.addEventListener("click", (event) => {
  if (event.target === factEvidenceDialog) {
    closeFactEvidenceDialog();
  }
});
deleteSessionDialog?.addEventListener("click", (event) => {
  if (event.target === deleteSessionDialog) {
    closeDeleteSessionDialog();
  }
});
deleteMemoryDialog?.addEventListener("click", (event) => {
  if (event.target === deleteMemoryDialog) {
    closeDeleteMemoryDialog();
  }
});
contextMemoryDialog?.addEventListener("click", (event) => {
  if (event.target === contextMemoryDialog) {
    closeContextMemoryDialog();
  }
});
whatsappStyleDialog?.addEventListener("click", (event) => {
  if (event.target === whatsappStyleDialog) {
    closeWhatsappStyleDialog();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeMobileHistorySheet();
  if (factEvidenceDialog && !factEvidenceDialog.hidden) {
    closeFactEvidenceDialog();
  }
  if (deleteSessionDialog && !deleteSessionDialog.hidden) {
    closeDeleteSessionDialog();
  }
  if (deleteMemoryDialog && !deleteMemoryDialog.hidden) {
    closeDeleteMemoryDialog();
  }
  if (contextMemoryDialog && !contextMemoryDialog.hidden) {
    closeContextMemoryDialog();
  }
  if (whatsappStyleDialog && !whatsappStyleDialog.hidden) {
    closeWhatsappStyleDialog();
  }
  closeDataPointFeedbackDialog();
});
loginGoogle?.addEventListener("click", signInWithGoogle);
authScreenLogin?.addEventListener("click", signInWithGoogle);
logoutUser?.addEventListener("click", signOutUser);
authUser?.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleAccountMenu();
});
accountMenuProfile?.addEventListener("click", () => {
  closeAccountMenu();
  openProfilePage();
});
accountMenuSignout?.addEventListener("click", signOutUser);
window.addEventListener("resize", updateAppHeaderHeight);
window.addEventListener("resize", scheduleFeedbackPopoverPositionSync);
chatLog?.addEventListener("scroll", scheduleFeedbackPopoverPositionSync);
if (window.ResizeObserver && appHeader) {
  const appHeaderObserver = new ResizeObserver(updateAppHeaderHeight);
  appHeaderObserver.observe(appHeader);
}
menuButton?.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleAppMenu();
});
document.querySelectorAll("[data-nav]").forEach((link) => {
  link.addEventListener("click", (event) => {
    const targetScreen = link.dataset.nav;
    if (!targetScreen || !routes[targetScreen]) return;
    event.preventDefault();
    closeAppMenu();
    window.history.pushState({}, "", link.getAttribute("href") || "/app");
    showScreen(targetScreen);
    if (targetScreen === "interview") {
      restoreOrStartConversation();
      focusChatInput();
    }
  });
});
profileGender?.addEventListener("change", () => {
  setFieldError(profileGender, "");
  updateInterestedInDefault();
});
profileInterestedIn?.addEventListener("change", syncBasicsOptionButtons);
basicsOptionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectBasicsOption(button.dataset.profileOption, button.dataset.value);
  });
});
syncBasicsOptionButtons();
setDobBounds();
loadIndiaLocations().catch((error) => {
  if (datingBasicsStatus) {
    datingBasicsStatus.textContent = error.message;
  }
});
onboardingNextStep?.addEventListener("click", goToNextOnboardingStep);
onboardingBackStep?.addEventListener("click", goToPreviousOnboardingStep);
accountGender?.addEventListener("change", updateAccountInterestedInDefault);
profileState?.addEventListener("change", () => {
  populateCitySelect(profileState, profileCity);
  setFieldError(profileState, "");
  setFieldError(profileCity, "");
});
accountState?.addEventListener("change", () => {
  populateCitySelect(accountState, accountCity);
});
profilePhoto?.addEventListener("change", previewSelectedPhotos);
profilePhotoTriggers.forEach((trigger) => {
  trigger.addEventListener("click", () => {
    pendingOnboardingPhotoSlot = Number(trigger.dataset.profilePhotoTrigger) || 0;
    profilePhoto?.click();
  });
});
[basicsName, profileDob, profileGender, profileInterestedIn, profileState, profileCity, profilePhone].forEach((field) => {
  field?.addEventListener("input", () => setFieldError(field, ""));
  field?.addEventListener("change", () => setFieldError(field, ""));
});
accountPhoto?.addEventListener("change", uploadSelectedAccountPhoto);
accountPhotoTriggers.forEach((trigger) => {
  trigger.addEventListener("click", () => {
    pendingAccountPhotoSlot = Number(trigger.dataset.accountPhotoTrigger) || 0;
    accountPhoto?.click();
  });
});
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
  if (event.key === "Escape") {
    closeAppMenu();
    closeAccountMenu();
    closeContextPicker();
    closeFeedbackPopover();
    closeDataPointFeedbackDialog();
  }
});
document.addEventListener("click", (event) => {
  if (
    accountMenu &&
    !accountMenu.hidden &&
    !accountMenu.contains(event.target) &&
    !authUser?.contains(event.target)
  ) {
    closeAccountMenu();
  }
  if (
    appNav?.classList.contains("is-open") &&
    !appNav.contains(event.target) &&
    !menuButton?.contains(event.target)
  ) {
    closeAppMenu();
  }
  if (
    appShell?.classList.contains("history-sheet-open") &&
    chatSidebar &&
    !chatSidebar.contains(event.target) &&
    !openHistorySheet?.contains(event.target)
  ) {
    closeMobileHistorySheet();
  }
  if (activeFeedbackMessageIndex !== null && !event.target.closest(".message-feedback")) {
    closeFeedbackPopover();
  }
  if (
    activeFeedbackMessageIndex === null &&
    revealedFeedbackMessageIndex !== null &&
    isTouchFeedbackMode() &&
    !event.target.closest(".message.agent")
  ) {
    revealedFeedbackMessageIndex = null;
    renderMessages({ preserveScroll: true });
  }
  if (
    agentContextMenu &&
    agentContextButton &&
    !agentContextMenu.hidden &&
    !agentContextMenu.contains(event.target) &&
    !agentContextButton.contains(event.target)
  ) {
    closeContextPicker();
  }
});

bootApp();

async function bootApp() {
  await initializeAuth();

  const draftId = currentDraftIdFromPath();
  if (draftId) {
    showScreen("review");
    loadDraft(draftId);
  } else if (window.location.pathname === "/profile") {
    showScreen("profile");
  } else if (window.location.pathname === "/style") {
    showScreen("style");
  } else if (window.location.pathname === "/matches") {
    showScreen("matches");
  } else {
    if (window.location.pathname === "/usage") {
      window.history.replaceState({}, "", "/app");
    }
    showScreen("interview");
    restoreOrStartConversation();
  }
}
