import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { apiFetch } from "../../../lib/api";
import { VIBE_STEPS, type Vibe, vibeStepIndex } from "../vibe";

// Matching is not built yet; until then this shows how close the user is to it.
export function MatchesPage({ onVibe }: { onVibe: () => void }) {
  const [vibe, setVibe] = useState<Vibe | null>(null);

  useEffect(() => {
    apiFetch("/api/me/vibe")
      .then((response) => (response.ok ? response.json() : null))
      .then((data: Vibe | null) => setVibe(data))
      .catch(() => undefined);
  }, []);

  const step = vibe ? vibeStepIndex(vibe.milestone) : -1;
  const ready = step >= vibeStepIndex("ready_to_match");
  const progress = !vibe
    ? null
    : ready
      ? "Omi knows you well enough. You'll be first in line when matches open."
      : step >= 0
        ? `You're at "${VIBE_STEPS[step].label}". Matches need "Ready to match".`
        : "Omi is just getting to know you. Keep chatting.";

  return (
    <section className="screen matches-screen mem">
      <header className="mem-head">
        <h1>Matches</h1>
        <p>People you'd actually get along with, found from the vibe Omi learns as you chat.</p>
      </header>
      <div className="mem-list matches-soon">
        <span className="state-view-mark" aria-hidden="true"><Users /></span>
        <strong>Matches are coming soon</strong>
        {progress ? <p>{progress}</p> : null}
        <button type="button" className="secondary-button" onClick={onVibe}>See your vibe</button>
      </div>
    </section>
  );
}
