import { ArrowRight, MapPin } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { OmirynLogo } from "../brand/OmirynLogo";

type AuthUser = { display_name?: string | null };
type LocationEstimate = { city?: string; region?: string; country?: string };

// Signup asks only what the app cannot work without: a name and the 18+ confirmation.
// Location is estimated from the connection and shown so the user can correct it; everything
// else is learned in conversation or set on the profile page.
export function QuickSetup() {
  const [displayName, setDisplayName] = useState("");
  const [adultConfirmed, setAdultConfirmed] = useState(false);
  const [estimate, setEstimate] = useState<LocationEstimate | null>(null);
  const [editingCity, setEditingCity] = useState(false);
  const [city, setCity] = useState("");
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
    apiFetch("/api/me/location-estimate")
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { estimate?: LocationEstimate | null } | null) => {
        if (!cancelled && data?.estimate?.city) setEstimate(data.estimate);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const placeLabel = estimate ? [estimate.city, estimate.region].filter(Boolean).join(", ") : "";
  const showCityInput = editingCity || !estimate;

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
        body: JSON.stringify({
          display_name: displayName.trim(),
          adult_confirmed: true,
          // Sent only when the user typed it; otherwise the estimate stays marked approximate.
          city: showCityInput && city.trim() ? city.trim() : null
        })
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
    <main className="quick-setup">
      <header className="quick-setup-header">
        <OmirynLogo />
      </header>
      <form className="quick-setup-card" onSubmit={start} noValidate>
        <p className="quick-setup-kicker">Just one quick step</p>
        <h1>What should Omi call you?</h1>
        <p className="quick-setup-intro">Then you can start talking. Omi will get to know you as you go.</p>

        <label className="quick-setup-label" htmlFor="display-name">Your name</label>
        <input
          id="display-name"
          className="quick-setup-input"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="Your name"
          autoComplete="name"
          maxLength={120}
        />

        <div className="quick-setup-location">
          {showCityInput ? (
            <>
              <label className="quick-setup-label" htmlFor="city">
                Where are you? <span className="quick-setup-optional">Optional</span>
              </label>
              <input
                id="city"
                className="quick-setup-input"
                value={city}
                onChange={(event) => setCity(event.target.value)}
                placeholder={placeLabel || "Your city"}
                autoComplete="address-level2"
                maxLength={120}
              />
              <p className="quick-setup-hint">Helps us find friends near you. You can change it anytime.</p>
            </>
          ) : (
            <p className="quick-setup-place">
              <MapPin aria-hidden="true" />
              <span>Around <strong>{placeLabel}</strong></span>
              <button type="button" onClick={() => { setEditingCity(true); setCity(estimate?.city || ""); }}>
                Change
              </button>
            </p>
          )}
        </div>

        <label className="quick-setup-check">
          <input type="checkbox" checked={adultConfirmed} onChange={(event) => setAdultConfirmed(event.target.checked)} />
          <span>I'm 18 or older</span>
        </label>

        {error ? <p className="quick-setup-error" role="alert">{error}</p> : null}

        <button className="quick-setup-submit" type="submit" disabled={submitting}>
          {submitting ? "Opening chat..." : "Start chatting"}
          {submitting ? null : <ArrowRight aria-hidden="true" />}
        </button>
      </form>
    </main>
  );
}
