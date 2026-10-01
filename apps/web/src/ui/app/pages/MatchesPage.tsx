import { useEffect, useState } from "react";
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

  return <section className="screen matches-screen"><div className="matches-coming-soon"><div className="coming-soon-mark" aria-hidden="true"><span /></div><p className="eyebrow">Matches</p><h1>Coming soon.</h1><p>Omiryn will introduce you to people you'd actually get along with, based on the vibe Omi learns as you chat.</p>{progress ? <p className="matches-progress">{progress}</p> : null}<button type="button" className="vibe-chat-button" onClick={onVibe}>See your vibe</button></div></section>;
}
