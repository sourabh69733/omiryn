import { type FormEvent, useEffect, useState } from "react";
import { Bug, Headphones, Lock, Mail, MessageCircle, Send, Shield, Users } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import type { AuthUser } from "../types";

type ContactCategory = "feedback" | "bug" | "support" | "privacy" | "safety";

const contactCategories: Array<{ id: ContactCategory; label: string; icon: typeof MessageCircle }> = [
  { id: "feedback", label: "Feedback", icon: MessageCircle },
  { id: "bug", label: "Bug", icon: Bug },
  { id: "support", label: "Support", icon: Headphones },
  { id: "privacy", label: "Privacy", icon: Lock },
  { id: "safety", label: "Safety", icon: Shield },
];

export function ContactPage({ user }: { user: AuthUser | null }) {
  const [category, setCategory] = useState<ContactCategory>("feedback");
  const [message, setMessage] = useState("");
  const [allowContact, setAllowContact] = useState(true);
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
        allow_contact: allowContact,
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
    setFeedbackStatus("Message sent. We will review it soon.");
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
    setConnectStatus(`${channel === "whatsapp" ? "WhatsApp" : "Discord"} invite request sent. We will review it soon.`);
  }

  return (
    <section className="screen contact-screen">
      <div className="contact-shell">
        <div className="screen-copy compact contact-title">
          <p className="eyebrow">Contact</p>
          <h1>Reach Omiryn.</h1>
          <p>Share feedback, report an issue, ask for support, or request a community invite.</p>
        </div>
        <form className="contact-feedback-panel" onSubmit={submitContact}>
          <div className="contact-panel-heading">
            <span className="contact-panel-icon"><MessageCircle size={22} /></span>
            <div><h2>Tell us what happened</h2><p>Choose a category and leave the details so we can understand and help.</p></div>
          </div>
          <div className="contact-category-row" role="radiogroup" aria-label="Feedback category">
            {contactCategories.map((item) => {
              const Icon = item.icon;
              return <button className={category === item.id ? "active" : ""} type="button" role="radio" aria-checked={category === item.id} key={item.id} onClick={() => setCategory(item.id)}><Icon size={17} /><span>{item.label}</span></button>;
            })}
          </div>
          <label className="contact-message-field">
            <span className="sr-only">Message or query</span>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={7} maxLength={2000} placeholder="Tell us what happened or what you would like to share..." />
            <small>{message.length}/2000</small>
          </label>
          <div className="contact-form-footer">
            <div className="contact-form-options">
              <p><Mail size={16} /> <span>From account: <strong>{email}</strong></span></p>
              <label><input type="checkbox" checked={allowContact} onChange={(event) => setAllowContact(event.target.checked)} /> <span>Allow Omiryn to contact me about this request.</span></label>
            </div>
            <button className="contact-send-button" type="submit" disabled={!canSend || sending}><Send size={17} /><span>{sending ? "Sending..." : "Send"}</span></button>
          </div>
          {feedbackStatus ? <p className="contact-status" role="status">{feedbackStatus}</p> : null}
        </form>
        <section className="contact-connect-panel" aria-labelledby="stay-connected-title">
          <div className="contact-panel-heading">
            <span className="contact-panel-icon"><Users size={22} /></span>
            <div><h2 id="stay-connected-title">Stay connected</h2><p>Other ways to reach us and get product updates.</p></div>
          </div>
          <div className="contact-connect-list">
            <a className="contact-connect-row" href="mailto:sourabhsahu69733@gmail.com"><span className="connect-icon email"><Mail size={20} /></span><span><strong>Email support</strong><small>Reach us directly by email.</small></span><em>Email us</em></a>
            <button className={`contact-connect-row ${requestedInvites.whatsapp ? "is-confirmed" : ""}`} type="button" onClick={() => void requestInvite("whatsapp")} disabled={Boolean(inviteChannel) || requestedInvites.whatsapp}><span className="connect-icon whatsapp">WA</span><span><strong>WhatsApp updates</strong><small>Request product updates and important announcements.</small></span><em className="green">{requestedInvites.whatsapp ? "Requested" : inviteChannel === "whatsapp" ? "Sending..." : "Request invite"}</em></button>
            <button className={`contact-connect-row ${requestedInvites.discord ? "is-confirmed" : ""}`} type="button" onClick={() => void requestInvite("discord")} disabled={Boolean(inviteChannel) || requestedInvites.discord}><span className="connect-icon discord">D</span><span><strong>Discord community</strong><small>Join community discussions after a quick review.</small></span><em>{requestedInvites.discord ? "Requested" : inviteChannel === "discord" ? "Sending..." : "Invite after review"}</em></button>
          </div>
          {connectStatus ? <p className="contact-status contact-connect-status" role="status">{connectStatus}</p> : null}
        </section>
      </div>
    </section>
  );
}

