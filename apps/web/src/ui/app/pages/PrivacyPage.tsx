// Plain-language account privacy guide. It describes current behavior, not planned controls.
import {
  ArrowRight,
  Bot,
  Brain,
  Check,
  ChevronLeft,
  Download,
  Eraser,
  LockKeyhole,
  MessageCircle,
  ShieldCheck,
  Trash2,
  User,
  UserX,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { Notice } from "../StateView";
import type { Consent } from "../vibe";

type PrivacyPageProps = {
  onProfile: () => void;
  onMemories: () => void;
  onContact: () => void;
};

type Step = { id: string; icon: LucideIcon; title: string; short: string; detail: string };

// A message's path, one stop at a time.
const STEPS: Step[] = [
  {
    id: "send",
    icon: MessageCircle,
    title: "You write",
    short: "Sent encrypted",
    detail: "Your message travels to Omiryn over an encrypted connection, like a banking or chat app.",
  },
  {
    id: "reply",
    icon: Brain,
    title: "Omi replies",
    short: "Read by AI, not people",
    detail:
      "To reply, your message and what Omi knows about you go through our server and an AI model, the same way ChatGPT and other assistants work. No person reads it.",
  },
  {
    id: "store",
    icon: LockKeyhole,
    title: "It's saved",
    short: "Stored encrypted",
    detail:
      "Your chat and the memories Omi learns are stored encrypted. Nobody at Omiryn reads chats, and our team's tools never show message text.",
  },
  {
    id: "control",
    icon: Trash2,
    title: "You decide",
    short: "Delete any time",
    detail: "Delete a message or a chat and what Omi learned only from it goes too. Or clear everything Omi knows.",
  },
];

type Viewer = { icon: LucideIcon; who: string; sees: boolean; what: string };

const VIEWERS: Viewer[] = [
  { icon: User, who: "You", sees: true, what: "Everything you shared, and every memory Omi keeps." },
  { icon: Bot, who: "Omi", sees: true, what: "Your chats, to reply and remember what matters to you." },
  { icon: Users, who: "Omiryn's team", sees: false, what: "We don't read chats. Our tools never show message text." },
  { icon: UserX, who: "People you meet", sees: false, what: "Never your chats or memories. An introduction shares a few reasons, not your words." },
];

type Mode = "normal" | "temporary";

const MODE_ROWS: { label: string; normal: string; temporary: string }[] = [
  { label: "Saved", normal: "Yes, encrypted", temporary: "Only while it's open" },
  { label: "Omi learns from it", normal: "Yes, as memories you can see and fix", temporary: "Never" },
  { label: "In your chats", normal: "Yes", temporary: "No" },
  { label: "Deleted", normal: "When you delete it", temporary: "When you leave it, or after 24 hours without messages" },
];

export function PrivacyPage({ onProfile, onMemories, onContact }: PrivacyPageProps) {
  const [consent, setConsent] = useState<Consent | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [stepId, setStepId] = useState(STEPS[0].id);
  const [mode, setMode] = useState<Mode>("normal");
  const step = STEPS.find((item) => item.id === stepId) ?? STEPS[0];

  useEffect(() => {
    apiFetch("/api/me/consent")
      .then((response) => (response.ok ? response.json() : null))
      .then((value: Consent | null) => setConsent(value ?? { private_matching: false, asked: false, at: null }))
      .catch(() => setConsent({ private_matching: false, asked: false, at: null }));
  }, []);

  async function toggle(allowed: boolean) {
    setSaving(true);
    setError("");
    const response = await apiFetch("/api/me/consent", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ private_matching: allowed }) });
    if (response.ok) setConsent((await response.json()) as Consent);
    else setError(await apiErrorMessage(response, "Could not save your choice."));
    setSaving(false);
  }

  return (
    <section className="screen privacy-screen">
      <button type="button" className="pf-back" onClick={onProfile}><ChevronLeft aria-hidden="true" />Profile</button>

      <header className="privacy-intro">
        <span className="privacy-seal"><ShieldCheck aria-hidden="true" />Private by default</span>
        <h1>Your privacy with Omi</h1>
        <p>Share freely. Here is exactly what happens to what you say.</p>
      </header>

      <section className="privacy-card privacy-flow" aria-labelledby="privacy-path-title">
        <h2 id="privacy-path-title">How Omi uses your messages</h2>
        <p className="privacy-hint">Tap a step to follow a message.</p>
        <div className="privacy-steps" role="tablist" aria-label="A message's path">
          {STEPS.map((item, index) => {
            const Icon = item.icon;
            const selected = item.id === step.id;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                id={`privacy-step-${item.id}`}
                aria-selected={selected}
                aria-controls="privacy-step-detail"
                className={`privacy-step${selected ? " is-selected" : ""}`}
                onClick={() => setStepId(item.id)}
              >
                <span className="privacy-step-icon"><Icon aria-hidden="true" /></span>
                <span className="privacy-step-text">
                  <span className="privacy-step-number">{index + 1}</span>
                  <strong>{item.title}</strong>
                  <span>{item.short}</span>
                </span>
              </button>
            );
          })}
        </div>
        <p className="privacy-step-detail" id="privacy-step-detail" role="tabpanel" aria-labelledby={`privacy-step-${step.id}`} aria-live="polite">
          {step.detail}
        </p>
      </section>

      <section className="privacy-card" aria-labelledby="privacy-access-title">
        <h2 id="privacy-access-title">Who can see your chats</h2>
        <ul className="privacy-viewers">
          {VIEWERS.map((viewer) => {
            const Icon = viewer.icon;
            return (
              <li key={viewer.who} className={viewer.sees ? "sees" : "never"}>
                <span className="privacy-viewer-icon"><Icon aria-hidden="true" /></span>
                <div>
                  <strong>{viewer.who}</strong>
                  <span>{viewer.what}</span>
                </div>
                <span className="privacy-mark" aria-label={viewer.sees ? "Can see" : "Cannot see"}>
                  {viewer.sees ? <Check aria-hidden="true" /> : <X aria-hidden="true" />}
                </span>
              </li>
            );
          })}
        </ul>
        <p className="privacy-note-line">
          Chats are not end-to-end encrypted: Omi has to read a message to reply, so it passes through our server. Every AI assistant works this way today.
        </p>
      </section>

      <section className="privacy-card" aria-labelledby="privacy-modes-title">
        <h2 id="privacy-modes-title">Normal chat or Temporary Chat</h2>
        <div className="privacy-modes" role="radiogroup" aria-label="Chat type">
          <button type="button" role="radio" aria-checked={mode === "normal"} onClick={() => setMode("normal")}>Normal chat</button>
          <button type="button" role="radio" aria-checked={mode === "temporary"} onClick={() => setMode("temporary")}>Temporary Chat</button>
        </div>
        <dl className="privacy-mode-rows">
          {MODE_ROWS.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row[mode]}</dd>
            </div>
          ))}
        </dl>
        <p className="privacy-hint">
          {mode === "temporary"
            ? "Start one from the chat menu (⋯), then Temporary chat. Omi still knows you, it just learns nothing new."
            : "Omi remembers what matters so it can be a better friend. You can see and fix every memory."}
        </p>
      </section>

      <section className="privacy-card" aria-labelledby="privacy-control-title">
        <h2 id="privacy-control-title">What you can do</h2>
        <div className="privacy-controls">
          <button type="button" className="privacy-control" onClick={onMemories}>
            <Brain aria-hidden="true" /><span><strong>See and fix memories</strong><span>Correct or delete anything Omi remembers.</span></span><ArrowRight aria-hidden="true" className="privacy-go" />
          </button>
          <div className="privacy-control">
            <Trash2 aria-hidden="true" /><span><strong>Delete a message or chat</strong><span>Hold a message, or use its ⋯ menu. What Omi learned only from it goes too.</span></span>
          </div>
          <div className="privacy-control">
            <Eraser aria-hidden="true" /><span><strong>Clear everything Omi knows</strong><span>Select all messages in a chat, then delete and tick the clear option.</span></span>
          </div>
          <button type="button" className="privacy-control" onClick={onProfile}>
            <Download aria-hidden="true" /><span><strong>Get a copy or delete your account</strong><span>From Profile. Backups can take a little longer to clear.</span></span><ArrowRight aria-hidden="true" className="privacy-go" />
          </button>
        </div>
      </section>

      <section className="privacy-consent" aria-labelledby="privacy-consent-title">
        <div>
          <h2 id="privacy-consent-title">Private topics in matching</h2>
          <p>Your beliefs, stories and deal-breakers are never shown to anyone. When this is on, Omi can use them to find people you'd click with. Turn it off any time; it stops at once.</p>
        </div>
        <label className="privacy-switch">
          <input type="checkbox" role="switch" checked={Boolean(consent?.private_matching)} disabled={!consent || saving} onChange={(event) => void toggle(event.target.checked)} />
          <span aria-hidden="true" />
          <span className="sr-only">Use private topics for matching</span>
        </label>
      </section>
      {error ? <Notice tone="error">{error}</Notice> : null}

      <footer className="privacy-footer">
        <p>Never share passwords, card numbers or ID numbers in a chat.</p>
        <p>Want the full details? Read our <a href="https://omiryn.com/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a>. If something is unclear, <button type="button" onClick={onContact}>ask us directly</button>.</p>
      </footer>
    </section>
  );
}
