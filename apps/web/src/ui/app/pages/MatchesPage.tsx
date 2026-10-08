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

  return (
    <section className="screen matches-screen mem">
      <header className="mem-head">
        <h1>Matches</h1>
        <p>People you'd actually get along with, found from the vibe Omi learns as you chat.</p>
      </header>
      {/* An illustration of a future introduction, clearly marked; never a real person. */}
      <article className="match-example" aria-label="Example introduction">
        <span className="match-example-tag">Example</span>
        <div className="match-example-person">
          <span className="match-example-avatar" aria-hidden="true" />
          <div>
            <strong>Someone near you</strong>
            <small>Also into late-night building</small>
          </div>
        </div>
        <p className="match-example-why"><span>You'd click on</span>terrible puns, hackathons, and keeping plans</p>
        <p className="match-example-why"><span>Fine with your difference</span>an early bird who likes your night-owl energy</p>
        <div className="match-example-actions" aria-hidden="true"><span>Not for me</span><span className="is-primary">Say hi</span></div>
      </article>
      <ol className="match-steps">
        <li><strong>Talk with Omi</strong><span>Like you would with a friend. No forms.</span></li>
        <li><strong>Omi finds someone</strong><span>Who fits how you laugh, live and think.</span></li>
        <li><strong>You both say yes</strong><span>Then the chat opens, with an easy start.</span></li>
      </ol>
      <div className="mem-list matches-soon">
        <strong>Matches are coming soon</strong>
        {progress ? <p>{progress}</p> : null}
        <button type="button" className="secondary-button" onClick={onVibe}>See your vibe</button>
      </div>
    </section>
  );
}
