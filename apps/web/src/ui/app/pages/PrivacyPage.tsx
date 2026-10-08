// Plain-language account privacy guide. It describes current behavior, not planned controls.
import { ArrowRight, Brain, LockKeyhole, MessageCircle } from "lucide-react";

type PrivacyPageProps = {
  onProfile: () => void;
  onMemories: () => void;
  onContact: () => void;
};

export function PrivacyPage({ onProfile, onMemories, onContact }: PrivacyPageProps) {
  return (
    <section className="screen privacy-screen">
      <nav className="pf-tabs" aria-label="Profile sections"><button type="button" onClick={onProfile}>Profile</button><span aria-current="page">Privacy</span></nav>

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

      <div className="privacy-details">
        <section aria-labelledby="privacy-saved-title">
          <h2 id="privacy-saved-title">What is saved?</h2>
          <p>Your chats, your profile, and the memories Omi learns from them. If you upload a chat or add other context, that is saved too and can shape Omi's replies.</p>
          <p>Your chats and memories are encrypted and stored securely. Some processing runs on trusted partners, listed in our Privacy Policy.</p>
        </section>
        <section aria-labelledby="privacy-access-title">
          <h2 id="privacy-access-title">Who can read a chat?</h2>
          <p>Only you, and Omi so it can reply. We never read your messages. Our team only sees what you send us yourself, like feedback or a support request.</p>
          <p>We are building new technology to give you even more privacy.</p>
        </section>
        <section aria-labelledby="privacy-control-title">
          <h2 id="privacy-control-title">What can you control?</h2>
          <p>You can review, correct, or delete Omi's memories, choose how each memory is used, delete a chat, or delete your account and data. Deleting a chat also removes memories that came only from it.</p>
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
