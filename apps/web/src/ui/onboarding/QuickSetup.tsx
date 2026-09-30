import { ArrowRight } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { OmirynLogo } from "../brand/OmirynLogo";

type AuthUser = { display_name?: string | null };

// Signup asks only what the app cannot work without: a name and the 18+ confirmation.
// Location is estimated from the connection and confirmed later in chat; everything else
// is learned in conversation or set on the profile page.
export function QuickSetup() {
  const [displayName, setDisplayName] = useState("");
  const [adultConfirmed, setAdultConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/auth/me")
      .then((response) => (response.ok ? response.json() : null))
      .then((user: AuthUser | null) => {
        const name = user?.display_name?.trim();
        if (name && !cancelled) setDisplayName((current) => current.trim() || name);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  async function start(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    if (!displayName.trim()) {
      setError("Tell us what to call you.");
      return;
    }
    if (!adultConfirmed) {
      setError("Omiryn is for people aged 18 and above.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const basics = await apiFetch("/api/me/basics", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim(), adult_confirmed: true })
      });
      if (!basics.ok) throw new Error(await apiErrorMessage(basics, "Could not save your details."));
      const created = await apiFetch("/api/agent/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_mode: "know_me", agent_tone: "warm" })
      });
      if (!created.ok) throw new Error(await apiErrorMessage(created, "Could not start your first chat."));
      const conversation = (await created.json()) as { id: string };
      const nextUrl = new URL("/", window.location.origin);
      nextUrl.searchParams.set("conversation_id", conversation.id);
      window.location.replace(nextUrl.toString());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not open the app. Please retry.");
      setSubmitting(false);
    }
  }

  return (
    <main className="setup-page quick-setup">
      <header className="setup-header">
        <OmirynLogo />
      </header>
      <section className="setup-content">
        <form className="setup-card" onSubmit={start}>
          <div className="card-heading">
            <h2>Welcome to Omiryn</h2>
            <p>Talk with Omi, and it finds friends you'd actually get along with.</p>
          </div>
          <div className="form-section">
            <label className="field-label" htmlFor="display-name">What should we call you?</label>
            <input
              id="display-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Your name"
              autoComplete="name"
              maxLength={120}
              autoFocus
            />
            <label className="adult-check">
              <input
                type="checkbox"
                checked={adultConfirmed}
                onChange={(event) => setAdultConfirmed(event.target.checked)}
              />
              <span>I'm 18 or older</span>
            </label>
          </div>
          <footer className="form-actions">
            <span />
            <button className="primary-button" type="submit" disabled={submitting}>
              {submitting ? "Opening chat..." : "Start chatting"} <ArrowRight />
            </button>
          </footer>
          {error ? <p className="submit-error" role="alert">{error}</p> : null}
        </form>
      </section>
    </main>
  );
}
