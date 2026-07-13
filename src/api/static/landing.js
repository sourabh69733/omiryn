const root = document.documentElement;
const toggle = document.querySelector("#theme-toggle");
const icon = document.querySelector("#theme-icon");
const themeKey = "omiryn.landing.theme";
const localHosts = new Set(["localhost", "127.0.0.1", "::1", "0.0.0.0"]);

function appUrl() {
  const appOrigin = root.dataset.appOrigin || "https://app.omiryn.com";
  const configuredLocalOrigin = root.dataset.localAppOrigin;
  const localAppPort = root.dataset.localAppPort || window.location.port || "8001";
  const isLoopback = localHosts.has(window.location.hostname);
  const isLocalTunnel = !isLoopback && window.location.hostname.startsWith("local");

  if (isLoopback || isLocalTunnel) {
    const localOrigin = configuredLocalOrigin
      || (isLocalTunnel ? window.location.origin : `${window.location.protocol}//${window.location.hostname}:${localAppPort}`);
    return new URL("/app", localOrigin).toString();
  }
  return new URL("/app", appOrigin).toString();
}

function isAuthCallbackHash() {
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return hashParams.has("access_token") || hashParams.has("refresh_token") || hashParams.has("error");
}

if (window.location.pathname === "/" && isAuthCallbackHash()) {
  const target = new URL(appUrl());
  target.search = window.location.search;
  target.hash = window.location.hash;
  window.location.replace(target.toString());
}

document.querySelectorAll("[data-app-link]").forEach((link) => {
  link.href = appUrl();
});

function systemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setTheme(theme) {
  root.dataset.theme = theme;
  icon.textContent = theme === "dark" ? "☾" : "☼";
  toggle.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
}

const savedTheme = localStorage.getItem(themeKey);
setTheme(savedTheme || systemTheme());

toggle.addEventListener("click", () => {
  const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem(themeKey, nextTheme);
  setTheme(nextTheme);
});
