// Admin shell: sign-in gate, sidebar routing, and one loader per page. Each page module gets a
// small context (root element, api helper, route params) and owns its own rendering and clicks.
import { adminFetch, ensureAdminSession, signInWithGoogle, signOut } from "./auth.js";
import { apiErrorMessage, esc } from "./ui.js";
import * as dashboard from "./pages/dashboard.js";
import * as people from "./pages/people.js";
import * as usage from "./pages/usage.js";
import * as system from "./pages/system.js";
import * as requests from "./pages/requests.js";
import * as pools from "./pages/pools.js";

const ROUTES = [
  { name: "dashboard", path: /^\/$/, page: dashboard, title: "Dashboard", subtitle: "How Omiryn is doing today and this week." },
  { name: "users", path: /^\/users(?:\/([^/]+))?\/?$/, page: people, title: "Users", subtitle: "Everyone who uses Omi. Counts and timing only: chat and memory text stay private." },
  { name: "usage", path: /^\/usage\/?$/, page: usage, title: "Usage & cost", subtitle: "Model calls, spend, speed and failures." },
  { name: "system", path: /^\/system\/?$/, page: system, title: "System", subtitle: "Background jobs, memory pipeline, channels, evals and the admin access log." },
  { name: "requests", path: /^\/requests\/?$/, page: requests, title: "Requests", subtitle: "Feedback, invites, data requests and app errors." },
  { name: "pools", path: /^\/pools\/?$/, page: pools, title: "Pools", subtitle: "Match pools: who is ready, suggested pairs and the introductions you confirmed." },
];

const adminAuth = document.querySelector("#admin-auth");
const adminLoading = document.querySelector("#admin-loading");
const adminSignInPanel = document.querySelector("#admin-sign-in-panel");
const adminAccessDenied = document.querySelector("#admin-access-denied");
const adminAuthMessage = document.querySelector("#admin-auth-message");
const adminApp = document.querySelector("#admin-app");
const adminSignIn = document.querySelector("#admin-sign-in");
const adminSignOut = document.querySelector("#admin-sign-out");
const adminDeniedSignOut = document.querySelector("#admin-denied-sign-out");
const refreshButton = document.querySelector("#refresh-admin");
const pageRoot = document.querySelector("#page");
const pageTitle = document.querySelector("#page-title");
const pageSubtitle = document.querySelector("#page-subtitle");
const statusEl = document.querySelector("#admin-status");
const navToggle = document.querySelector("#nav-toggle");

let loadToken = 0;
let cleanup = null;

export function routeFor(pathname) {
  for (const route of ROUTES) {
    const match = route.path.exec(pathname);
    if (match) return { route, params: match.slice(1).filter(Boolean).map(decodeURIComponent) };
  }
  return { route: ROUTES[0], params: [] };
}

function showLoading() {
  adminAuth.hidden = false;
  adminLoading.hidden = false;
  adminSignInPanel.hidden = true;
  adminAccessDenied.hidden = true;
  adminApp.hidden = true;
}

function showSignIn(message = "Use the Google account with admin access.") {
  adminAuth.hidden = false;
  adminLoading.hidden = true;
  adminSignInPanel.hidden = false;
  adminAccessDenied.hidden = true;
  adminApp.hidden = true;
  adminAuthMessage.textContent = message;
}

function showAccessDenied() {
  adminAuth.hidden = false;
  adminLoading.hidden = true;
  adminSignInPanel.hidden = true;
  adminAccessDenied.hidden = false;
  adminApp.hidden = true;
}

function showAdminApp() {
  adminAuth.hidden = true;
  adminApp.hidden = false;
}

function handleAuthResponse(response) {
  if (response.status === 401) {
    showSignIn("Your session has ended. Sign in again to continue.");
    throw new Error("Sign in required.");
  }
  if (response.status === 403) {
    showAccessDenied();
    throw new Error("Your account does not have admin access.");
  }
  return response;
}

/** JSON from an admin endpoint, with sign-in and error handling in one place. */
async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) };
  const response = handleAuthResponse(await adminFetch(path, { ...options, headers: { ...headers, ...(options.headers || {}) } }));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiErrorMessage(data.detail, "The request failed."));
  return data;
}

function setStatus(message, tone = "") {
  statusEl.textContent = message;
  statusEl.dataset.tone = tone;
}

export function navigate(path, { replace = false } = {}) {
  if (path === window.location.pathname + window.location.search) return;
  window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  void loadPage();
}

async function loadPage({ quiet = false } = {}) {
  const token = ++loadToken;
  const { route, params } = routeFor(window.location.pathname);
  document.querySelectorAll("[data-route]").forEach((link) => {
    const active = link.dataset.route === route.name;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.body.classList.remove("nav-open");
  pageTitle.textContent = route.title;
  pageSubtitle.textContent = route.subtitle;
  document.title = `${route.title} · Omiryn Admin`;
  if (cleanup) cleanup();
  cleanup = null;
  setStatus("Loading…", "busy");
  const started = performance.now();
  try {
    const context = {
      root: pageRoot,
      params,
      query: new URLSearchParams(window.location.search),
      api,
      navigate,
      setStatus,
      quiet,
      isCurrent: () => token === loadToken,
    };
    cleanup = (await route.page.render(context)) || null;
    if (token !== loadToken) return;
    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    setStatus(`Updated ${new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })} · ${seconds}s`);
  } catch (error) {
    if (token !== loadToken) return;
    pageRoot.innerHTML = `<div class="page-error"><strong>Could not load this page.</strong><p>${esc(error.message)}</p><button type="button" data-retry>Try again</button></div>`;
    setStatus(error.message, "bad");
  }
}

async function startAdminApp() {
  showLoading();
  try {
    if (!(await ensureAdminSession())) {
      showSignIn();
      return;
    }
    showAdminApp();
    await loadPage();
  } catch (error) {
    showSignIn(error.message);
  }
}

// In-app links: anything marked data-link (or the sidebar) changes the route without a reload.
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-link], a[data-route]");
  if (link && link.origin === window.location.origin && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
    event.preventDefault();
    navigate(link.pathname + link.search);
    return;
  }
  if (event.target.closest("[data-retry]")) void loadPage();
});
window.addEventListener("popstate", () => void loadPage());

adminSignIn.addEventListener("click", async () => {
  showLoading();
  try {
    await signInWithGoogle();
  } catch (error) {
    showSignIn(error.message);
  }
});
adminSignOut.addEventListener("click", signOut);
adminDeniedSignOut.addEventListener("click", signOut);
window.addEventListener("omiryn:auth-required", () => showSignIn("Your session has ended. Sign in again to continue."));
refreshButton.addEventListener("click", () => void loadPage({ quiet: true }));
navToggle?.addEventListener("click", () => document.body.classList.toggle("nav-open"));

startAdminApp();
