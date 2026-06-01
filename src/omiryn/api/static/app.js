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

renderMessages();
setProfile(extractedProfiles[0]);
loadMatches();
