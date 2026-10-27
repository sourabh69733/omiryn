// Plain-language account privacy guide. It describes current behavior, not planned controls.
import { ArrowRight, Brain, ChevronLeft, LockKeyhole, MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { Notice } from "../StateView";
import type { Consent } from "../vibe";

type PrivacyPageProps = {
  onProfile: () => void;
  onMemories: () => void;
  onContact: () => void;
};

export function PrivacyPage({ onProfile, onMemories, onContact }: PrivacyPageProps) {
  const [consent, setConsent] = useState<Consent | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
        <h1>Your privacy with Omi</h1>
        <p>Your messages help Omi reply and get to know you. Here is what happens to them.</p>
      </header>

      <section className="privacy-path" aria-labelledby="privacy-path-title">
        <h2 id="privacy-path-title">How Omi uses your messages</h2>
        <ol>
          <li><MessageCircle aria-hidden="true" /><div><strong>You write</strong><span>Your message is sent securely to Omiryn.</span></div></li>
          <li><Brain aria-hidden="true" /><div><strong>Omi replies</strong><span>Omi reads your message, along with what it knows about you, to write a reply.</span></div></li>
          <li><LockKeyhole aria-hidden="true" /><div><strong>Omi remembers</strong><span>Your chat is saved, with the things worth remembering about you.</span></div></li>
        </ol>
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

      <div className="privacy-details">
        <section aria-labelledby="privacy-saved-title">
          <h2 id="privacy-saved-title">What is saved?</h2>
          <p>Your chats, your profile, and the memories Omi learns from them. If you upload a chat or add other context, that is saved too and can shape Omi's replies.</p>
          <p>Your chats and memories are encrypted and stored securely. Some processing runs on trusted partners, listed in our Privacy Policy.</p>
        </section>
        <section aria-labelledby="privacy-access-title">
          <h2 id="privacy-access-title">Who can read a chat?</h2>
          <p>You, and Omi so it can reply. Your messages are encrypted, but Omi has to read them to reply, so they are not end-to-end encrypted. This means the few people who run Omiryn's servers could technically access them.</p>
          <p>We don't. Reading your chats is not part of anyone's job here, and access to our servers is limited. Our team only sees what you send us yourself, like feedback or a support request.</p>
          <p>We are building technology so that one day even we can't access your messages.</p>
        </section>
        <section aria-labelledby="privacy-control-title">
          <h2 id="privacy-control-title">What can you control?</h2>
          <p>You can review, correct, or delete Omi's memories, choose how each memory is used, delete a message or a whole chat, clear everything Omi knows about you, or delete your account and data. Deleting messages or a chat also removes memories that came only from them.</p>
          <p>For something you don't want remembered, start a Temporary Chat from the chat menu. Omi learns nothing from it, and it is deleted when you leave.</p>
          <p>You can request a copy of your data from Profile. Some copies, like backups, can take a little longer to be fully removed.</p>
          <button type="button" className="privacy-action" onClick={onMemories}>Review Omi's memories <ArrowRight aria-hidden="true" /></button>
        </section>
      </div>

      <footer className="privacy-footer">
        <p>Want the full details? Read our <a href="https://omiryn.com/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a>. If something is unclear, <button type="button" onClick={onContact}>ask us directly</button>.</p>
      </footer>
    </section>
  );
}
