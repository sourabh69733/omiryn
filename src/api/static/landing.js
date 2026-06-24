const root = document.documentElement;
const toggle = document.querySelector("#theme-toggle");
const icon = document.querySelector("#theme-icon");
const themeKey = "omiryn.landing.theme";
const localHosts = new Set(["localhost", "127.0.0.1", "::1", "0.0.0.0"]);

function appUrl() {
  if (localHosts.has(window.location.hostname)) {
    return `${window.location.origin}/app`;
  }
  return "https://app.omiryn.com";
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
