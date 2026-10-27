import { Check, Lock, MessageCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { Notice, StateView } from "../StateView";
import { VIBE_AREA_LABELS, VIBE_STEPS, type Consent, type Vibe, type VibeArea, confidenceLevel, evidenceChatPath, privateLine, proofSummary, strengthLabel, vibeStepIndex } from "../vibe";

// The user's vibe: what Omi has understood about who they'd get along with.
// Everything here is learned in chat; the user can only remove a line that is wrong.
export function VibePage({ onChat }: { onChat: () => void }) {
  const [vibe, setVibe] = useState<Vibe | null>(null);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [openWhy, setOpenWhy] = useState<string | null>(null);
  const [savingConsent, setSavingConsent] = useState(false);

  function load() {
    setLoadError("");
    apiFetch("/api/me/vibe")
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load your vibe."));
        setVibe((await response.json()) as Vibe);
      })
      .catch((caught) => setLoadError(caught instanceof Error ? caught.message : "Could not load your vibe."));
  }

  useEffect(load, []);

  async function remove(area: VibeArea) {
    setRemoving(area.id);
    const response = await apiFetch(`/api/me/vibe/${area.id}`, { method: "DELETE" });
    if (response.ok) {
      setVibe((await response.json()) as Vibe);
      setNotice({ tone: "success", text: "Removed. Omi won't bring it back unless you say something new about it." });
    } else setNotice({ tone: "error", text: await apiErrorMessage(response, "Could not remove that line.") });
    setRemoving(null);
  }

  async function chooseConsent(allowed: boolean) {
    setSavingConsent(true);
    const response = await apiFetch("/api/me/consent", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ private_matching: allowed }) });
    if (response.ok) {
      const consent = (await response.json()) as Consent;
      setVibe((current) => (current ? { ...current, consent } : current));
    } else setNotice({ tone: "error", text: await apiErrorMessage(response, "Could not save your choice.") });
    setSavingConsent(false);
  }

  // Asked once, when Omi has learned something private; the answer can change on the Privacy page.
  const askConsent = Boolean(vibe && !vibe.consent?.asked && vibe.areas.some((area) => area.private && area.text));
  const reachedStep = vibe ? vibeStepIndex(vibe.milestone) : -1;
  const ready = vibe ? vibeStepIndex(vibe.milestone) >= vibeStepIndex("ready_to_match") : false;
  const nextStep = vibe?.next_milestone ? VIBE_STEPS.find((step) => step.id === vibe.next_milestone) : null;

  return (
    <section className="screen vibe-screen mem">
      <header className="mem-head">
        <h1>Your vibe</h1>
        <p>What Omi has picked up about who you'd get along with. It's how we'll find you friends.</p>
      </header>

      {!vibe && !loadError ? <StateView kind="loading" title="Loading your vibe…" /> : null}
      {loadError ? <StateView kind="error" title="Couldn't load your vibe" detail={loadError} onRetry={load} /> : null}
      {notice ? <Notice tone={notice.tone}>{notice.text}</Notice> : null}

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

          {(["basics", "deeper"] as const).map((stage) => {
            const areas = vibe.areas.filter((area) => area.stage === stage);
            const known = areas.filter((area) => area.text);
            const open = areas.filter((area) => !area.text);
            return (
            <section className="vibe-group" key={stage}>
              <h2>{stage === "basics" ? "The basics" : "Going deeper"}</h2>
              {stage === "deeper" && askConsent ? (
                <div className="vibe-consent" role="group" aria-labelledby="vibe-consent-title">
                  <p id="vibe-consent-title"><Lock aria-hidden="true" /><strong>Your private topics</strong></p>
                  <p>Your beliefs, stories and deal-breakers are never shown to anyone. Can Omi use them to find people you'd click with?</p>
                  <div className="vibe-consent-actions">
                    <button type="button" onClick={() => void chooseConsent(true)} disabled={savingConsent}>Allow</button>
                    <button type="button" className="is-quiet" onClick={() => void chooseConsent(false)} disabled={savingConsent}>Not now</button>
                  </div>
                  <small>You can change this any time in Profile, under How Omi uses your data.</small>
                </div>
              ) : null}
              {known.length ? (
              <div className="vibe-cards">
                {known.map((area) => (
                  <article className={`vibe-card ${area.text ? "is-known" : ""}`} key={area.id}>
                    <div className="vibe-card-top">
                      <h3>{VIBE_AREA_LABELS[area.id] || area.id}</h3>
                      {area.strength ? (
                        <button
                          type="button"
                          className={`vibe-strength is-level-${confidenceLevel(area.evidence_count, area.evidence_days)}`}
                          onClick={() => setOpenWhy(openWhy === area.id ? null : area.id)}
                          aria-expanded={openWhy === area.id}
                          title="See what you said"
                        >
                          {strengthLabel(area.strength)} <span aria-hidden="true">›</span>
                        </button>
                      ) : null}
                    </div>
                    <p>{area.text || "Not yet. Omi picks this up as you chat."}</p>
                    {area.private ? (
                      <p className="vibe-private">
                        <Lock aria-hidden="true" />
                        {privateLine(vibe.consent)}
                      </p>
                    ) : null}
                    {area.text && openWhy === area.id ? (
                      area.evidence.length ? (
                        <ul className="vibe-quotes" aria-label="What you said">
                          {/* <li className="vibe-proof-summary">{proofSummary(area.evidence_count, area.evidence_days)}</li> */}
                          {area.evidence.map((item) => (
                            <li key={`${item.conversation_id}:${item.message_index}`}>
                              <span>“{item.quote}”</span>
                              <small>
                                {item.sent_at ? new Date(item.sent_at).toLocaleDateString(undefined, { day: "numeric", month: "short" }) + " · " : ""}
                                <a href={evidenceChatPath(item)} onClick={(event) => { event.preventDefault(); openInChat(evidenceChatPath(item)); }}>Open in chat</a>
                              </small>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="vibe-no-proof">The messages behind this line are no longer available.</p>
                      )
                    ) : null}
                    {area.text ? (
                      <div className="vibe-card-actions">
                        <button type="button" className="vibe-remove" onClick={() => void remove(area)} disabled={removing === area.id} aria-label={`Remove: ${VIBE_AREA_LABELS[area.id] || area.id}`}>
                          <X aria-hidden="true" />
                          {removing === area.id ? "Removing…" : "Not right"}
                        </button>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
              ) : null}
              {open.length ? (
                <p className="vibe-open">
                  <span>{known.length ? "Still to learn:" : "Omi hasn't picked these up yet:"}</span>
                  {open.map((area) => <span className="vibe-open-chip" key={area.id}>{VIBE_AREA_LABELS[area.id] || area.id}{area.private ? <Lock aria-label="Private" /> : null}</span>)}
                </p>
              ) : null}
            </section>
            );
          })}
        </>
      ) : null}
    </section>
  );
}

function openInChat(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
