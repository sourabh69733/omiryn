const root = document.documentElement;
const toggle = document.querySelector("#theme-toggle");
const icon = document.querySelector("#theme-icon");
const themeKey = "omiryn.landing.theme";
const sessionKey = "omiryn.public.session";
const localHosts = new Set(["localhost", "127.0.0.1", "::1", "0.0.0.0"]);

function sessionId() {
  let value = localStorage.getItem(sessionKey);
  if (!value) {
    value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(sessionKey, value);
  }
  return value;
}

function track(eventName, metadata = {}) {
  const payload = {
    session_id: sessionId(),
    event_name: eventName,
    path: window.location.pathname,
    referrer: document.referrer || null,
    metadata: {
      ...metadata,
      title: document.title,
      search: window.location.search || "",
    },
  };
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ event: eventName, ...payload });
  const body = JSON.stringify(payload);
  if (navigator.sendBeacon) {
    navigator.sendBeacon("/api/public/events", new Blob([body], { type: "application/json" }));
    return;
  }
  fetch("/api/public/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => undefined);
}

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
  if (!toggle || !icon) return;
  root.dataset.theme = theme;
  icon.textContent = theme === "dark" ? "☾" : "☼";
  toggle.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
}

const savedTheme = localStorage.getItem(themeKey);
setTheme(savedTheme || systemTheme());

toggle?.addEventListener("click", () => {
  const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem(themeKey, nextTheme);
  setTheme(nextTheme);
  track("theme_changed", { theme: nextTheme });
});

track("page_view");

document.querySelectorAll("[data-track]").forEach((element) => {
  element.addEventListener("click", () => {
    track("cta_click", {
      label: element.getAttribute("data-track"),
      text: element.textContent?.trim() || "",
      href: element.getAttribute("href") || "",
    });
  });
});

const sectionObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const id = entry.target.id || entry.target.getAttribute("aria-label") || "unnamed";
    if (entry.target.dataset.trackedView === "true") return;
    entry.target.dataset.trackedView = "true";
    track("section_view", { section: id });
  });
}, { threshold: 0.45 });

document.querySelectorAll("section[id]").forEach((section) => sectionObserver.observe(section));

document.querySelectorAll("form[data-form='lead']").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = form.querySelector(".form-status");
    const data = new FormData(form);
    const payload = {
      session_id: sessionId(),
      name: data.get("name") || null,
      contact: data.get("contact") || "",
      channel: data.get("channel") || "email",
      intent: data.get("intent") || "feedback",
      message: data.get("message") || null,
      metadata: {
        page: window.location.pathname,
        source: form.id || "public_form",
      },
    };
    if (status) status.textContent = "Sending...";
    try {
      const response = await fetch("/api/public/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error("Could not send.");
      form.reset();
      if (status) status.textContent = "Got it. I will follow up soon.";
      track("lead_submitted", { channel: payload.channel, intent: payload.intent });
    } catch {
      if (status) status.textContent = "Could not send right now. Please try again or email sourabhsahu69733@gmail.com.";
    }
  });
});
