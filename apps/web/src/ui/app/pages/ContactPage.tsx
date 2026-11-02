import { type FormEvent, useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import type { AuthUser } from "../types";

type ContactCategory = "feedback" | "bug" | "support" | "privacy" | "safety";

// One plain form: what it is about, the message, Send. Replies go to the account email.
const contactCategories: Array<{ id: ContactCategory; label: string }> = [
  { id: "feedback", label: "Feedback" },
  { id: "bug", label: "Something broke" },
  { id: "support", label: "I need help" },
  { id: "privacy", label: "Privacy" },
  { id: "safety", label: "Safety" },
];

const SUPPORT_EMAIL = "sourabhsahu69733@gmail.com";

export function ContactPage({ user }: { user: AuthUser | null }) {
  const [category, setCategory] = useState<ContactCategory>("feedback");
  const [message, setMessage] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [connectStatus, setConnectStatus] = useState("");
  const [sending, setSending] = useState(false);
  const [inviteChannel, setInviteChannel] = useState<"whatsapp" | "discord" | null>(null);
  const [requestedInvites, setRequestedInvites] = useState<Record<"whatsapp" | "discord", boolean>>({ whatsapp: false, discord: false });
  const email = user?.email || "your account email";
  const canSend = message.trim().length >= 10;

  useEffect(() => {
    trackAppEvent("feedback_opened", { page: "contact" }, { page: "contact" });
  }, []);

  async function submitContact(event: FormEvent) {
    event.preventDefault();
    if (!canSend || sending) return;
    setSending(true);
    setFeedbackStatus("");
    const response = await apiFetch("/api/me/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category,
        message: message.trim(),
        allow_contact: true,
        metadata: { page: "contact", source: "app_contact_page" },
      }),
    });
    setSending(false);
    if (!response.ok) {
      setFeedbackStatus(await apiErrorMessage(response, "Could not send your message."));
      return;
    }
    trackAppEvent("feedback_submitted", { category }, { page: "contact" });
    setMessage("");
    setFeedbackStatus(`Sent. We will reply to ${email}.`);
  }

  async function requestInvite(channel: "whatsapp" | "discord") {
    if (inviteChannel || requestedInvites[channel]) return;
    setInviteChannel(channel);
    setConnectStatus("");
    const response = await apiFetch("/api/me/community-invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel,
        allow_contact: true,
        metadata: { page: "contact", source: "stay_connected" },
      }),
    });
    setInviteChannel(null);
    if (!response.ok) {
      setConnectStatus(await apiErrorMessage(response, "Could not request invite."));
      return;
    }
    trackAppEvent("community_invite_requested", { channel }, { page: "contact" });
    setRequestedInvites((current) => ({ ...current, [channel]: true }));
    setConnectStatus(channel === "whatsapp" ? "Asked. We will add you to WhatsApp updates soon." : "Asked. We will send a Discord invite after a quick look.");
  }

  const inviteLabel = (channel: "whatsapp" | "discord", idle: string) =>
    requestedInvites[channel] ? "Asked" : inviteChannel === channel ? "Sending..." : idle;

  return (
    <section className="screen contact-screen">
      <div className="contact-shell">
        <header className="mem-head contact-title">
          <h1>Contact us</h1>
          <p>Feedback, a problem, a question. We read every message.</p>
        </header>

        <form className="contact-form" onSubmit={submitContact}>
          <label className="contact-field">
            <span>About</span>
            <select value={category} onChange={(event) => setCategory(event.target.value as ContactCategory)}>
              {contactCategories.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="contact-field contact-message-field">
            <span>Message</span>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={6} maxLength={2000} placeholder="What happened, or what would you like to tell us?" />
            {message.length > 1800 ? <small>{message.length}/2000</small> : null}
          </label>
          <div className="contact-actions">
            <button className="contact-send-button" type="submit" disabled={!canSend || sending}>{sending ? "Sending..." : "Send"}</button>
            <p className="contact-note">We reply to <strong>{email}</strong>.</p>
          </div>
          {feedbackStatus ? <p className="contact-status" role="status">{feedbackStatus}</p> : null}
        </form>

        <footer className="contact-other">
          <p>Or</p>
          <a href={`mailto:${SUPPORT_EMAIL}`}>Email us</a>
          <button type="button" onClick={() => void requestInvite("whatsapp")} disabled={Boolean(inviteChannel) || requestedInvites.whatsapp}>
            {inviteLabel("whatsapp", "Get WhatsApp updates")}
          </button>
          <button type="button" onClick={() => void requestInvite("discord")} disabled={Boolean(inviteChannel) || requestedInvites.discord}>
            {inviteLabel("discord", "Join the Discord")}
          </button>
          {connectStatus ? <p className="contact-status" role="status">{connectStatus}</p> : null}
        </footer>
      </div>
    </section>
  );
}
