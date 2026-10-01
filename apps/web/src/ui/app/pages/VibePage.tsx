import { Check, MessageCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { VIBE_AREA_LABELS, VIBE_STEPS, type Vibe, type VibeArea, vibeStepIndex } from "../vibe";

// The user's vibe: what Omi has understood about who they'd get along with.
// Everything here is learned in chat; the user can only remove a line that is wrong.
export function VibePage({ onChat }: { onChat: () => void }) {
  const [vibe, setVibe] = useState<Vibe | null>(null);
  const [status, setStatus] = useState("Loading your vibe…");
  const [removing, setRemoving] = useState<string | null>(null);
  const [openWhy, setOpenWhy] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/me/vibe")
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load your vibe."));
        setVibe((await response.json()) as Vibe);
        setStatus("");
      })
      .catch((caught) => setStatus(caught instanceof Error ? caught.message : "Could not load your vibe."));
  }, []);

  async function remove(area: VibeArea) {
    setRemoving(area.id);
    const response = await apiFetch(`/api/me/vibe/${area.id}`, { method: "DELETE" });
    if (response.ok) setVibe((await response.json()) as Vibe);
    else setStatus(await apiErrorMessage(response, "Could not remove that line."));
    setRemoving(null);
  }

  const reachedStep = vibe ? vibeStepIndex(vibe.milestone) : -1;
  const ready = vibe ? vibeStepIndex(vibe.milestone) >= vibeStepIndex("ready_to_match") : false;
  const nextStep = vibe?.next_milestone ? VIBE_STEPS.find((step) => step.id === vibe.next_milestone) : null;

  return (
    <section className="screen vibe-screen">
      <header className="vibe-header">
        <p className="eyebrow">Vibe</p>
        <h1>Your vibe</h1>
        <p>What Omi has picked up about who you'd get along with. It's how we'll find you friends.</p>
      </header>

      {status ? <p className="vibe-status" role="status">{status}</p> : null}

      {vibe ? (
        <>
          <ol className="vibe-path" aria-label="Progress">
            {VIBE_STEPS.map((step, index) => (
              <li key={step.id} className={index <= reachedStep ? "is-reached" : index === reachedStep + 1 ? "is-next" : ""}>
                <span className="vibe-path-dot" aria-hidden="true">{index <= reachedStep ? <Check /> : null}</span>
                <span className="vibe-path-label">{step.label}</span>
              </li>
            ))}
          </ol>

          <div className={`vibe-callout ${ready ? "is-ready" : ""}`}>
            <div>
              <strong>{ready ? "You're ready for matches." : vibe.known ? `Next: ${nextStep?.label.toLowerCase()}` : "Omi is just getting to know you."}</strong>
              <span>
                {ready
                  ? "Matching opens soon. Keep chatting, and Omi keeps getting sharper."
                  : "Just talk with Omi like you would with a friend. There are no forms or quizzes."}
              </span>
            </div>
            <button type="button" className="vibe-chat-button" onClick={onChat}>
              <MessageCircle aria-hidden="true" />
              Chat with Omi
            </button>
          </div>

          {(["basics", "deeper"] as const).map((stage) => (
            <section className="vibe-group" key={stage}>
              <h2>{stage === "basics" ? "The basics" : "Going deeper"}</h2>
              <div className="vibe-cards">
                {vibe.areas.filter((area) => area.stage === stage).map((area) => (
                  <article className={`vibe-card ${area.text ? "is-known" : ""}`} key={area.id}>
                    <div className="vibe-card-top">
                      <h3>{VIBE_AREA_LABELS[area.id] || area.id}</h3>
                      {area.strength ? (
                        <span className={`vibe-strength is-${area.strength}`} title={area.strength === "clear" ? "You've said this more than once." : "You've said this once; Omi will check as you chat."}>
                          {area.strength === "clear" ? "Clear" : "Said once"}
                        </span>
                      ) : null}
                    </div>
                    <p>{area.text || "Not yet. Omi picks this up as you chat."}</p>
                    {area.text && openWhy === area.id && area.quotes.length ? (
                      <ul className="vibe-quotes" aria-label="What you said">
                        {area.quotes.map((quote, index) => <li key={index}>“{quote}”</li>)}
                      </ul>
                    ) : null}
                    {area.text ? (
                      <div className="vibe-card-actions">
                        {area.quotes.length ? (
                          <button type="button" className="vibe-why" onClick={() => setOpenWhy(openWhy === area.id ? null : area.id)} aria-expanded={openWhy === area.id}>
                            {openWhy === area.id ? "Hide" : "Why?"}
                          </button>
                        ) : null}
                        <button type="button" className="vibe-remove" onClick={() => void remove(area)} disabled={removing === area.id} aria-label={`Remove: ${VIBE_AREA_LABELS[area.id] || area.id}`}>
                          <X aria-hidden="true" />
                          {removing === area.id ? "Removing…" : "Not right"}
                        </button>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ))}
        </>
      ) : null}
    </section>
  );
}
