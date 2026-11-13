import { useState } from "react";
import { apiFetch } from "../../lib/api";
import { trackAppEvent } from "../../lib/appLogger";
import { REPORT_REASONS, type MatchCard } from "./matches";

/* Report a person Omi offered or introduced. The report goes to the team with the reason; a block
   also keeps the two out of each other's future matches and closes their chat. The other person
   is told nothing beyond "not this week" or that it is off. */
export function ReportDialog({ card, page, onClose, onDone }: {
  card: MatchCard;
  page: string;
  onClose: () => void;
  /** The card as it is now, and the line to show the user. */
  onDone: (updated: MatchCard, message: string) => void;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [block, setBlock] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  async function send() {
    if (!reason || sending) return;
    setSending(true);
    setError("");
    const response = await apiFetch(`/api/me/matches/${card.pair_id}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, note: note.trim() || undefined, block }),
    }).catch(() => null);
    setSending(false);
    if (!response?.ok) {
      setError("Could not send the report. Nothing was sent, so please tell us through Contact.");
      return;
    }
    const data = await response.json();
    const updated: MatchCard = data.match ?? { ...card, status: block ? "blocked" : "declined" };
    trackAppEvent("match_reported", { reason, block }, { page });
    onDone(updated, block ? `Reported and blocked. ${card.name} won't come up again.` : "Reported. The team will look at it.");
  }

  return (
    <div className="confirm-overlay">
      <section className="confirm-dialog mt-pass" role="dialog" aria-modal="true" aria-labelledby="mt-report-title" onKeyDown={(event) => { if (event.key === "Escape" && !sending) onClose(); }}>
        <div className="confirm-copy">
          <h2 id="mt-report-title">Report {card.name}</h2>
          <p>Goes to the Omiryn team, never to {card.name}. Tell us what happened; a line is enough.</p>
        </div>
        <div className="mt-pass-reasons" role="group" aria-label="What happened">
          {REPORT_REASONS.map((item) => (
            <button key={item.id} type="button" className={reason === item.id ? "is-selected" : ""} aria-pressed={reason === item.id} onClick={() => setReason(item.id)}>{item.label}</button>
          ))}
        </div>
        <label className="mt-report-note">
          <span>Anything else (optional)</span>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} maxLength={1000} placeholder="What was said, what felt off." />
        </label>
        <label className="mt-report-block">
          <input type="checkbox" checked={block} onChange={(event) => setBlock(event.target.checked)} />
          <span>Also block {card.name}. You won't be matched again, and they won't be told why.</span>
        </label>
        {error ? <p className="mt-error" role="alert">{error}</p> : null}
        <div className="confirm-actions">
          <button type="button" className="secondary-button" disabled={sending} onClick={onClose}>Back</button>
          <button type="button" className="danger-button" disabled={sending || !reason} onClick={() => void send()}>{sending ? "Sending..." : block ? "Report and block" : "Send report"}</button>
        </div>
      </section>
    </div>
  );
}
