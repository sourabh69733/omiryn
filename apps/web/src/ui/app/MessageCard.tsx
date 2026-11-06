import type { ChatCard, ChatCardAction } from "./types";

// A card inside one of Omi's bubbles while it hosts a match: the plan, the consent to share a
// number, the day-3 check-in, or the ask. Omi writes the words; code gives it the facts. Tapping
// an action sends that action's reply as the user's message and the card settles on the answer.
type Props = { card: ChatCard; busy?: boolean; disabled?: boolean; onAction: (action: ChatCardAction) => void };

const EYEBROWS: Record<ChatCard["kind"], string> = {
  match_ask: "Someone you might click with",
  match_plan: "A first meet",
  match_consent: "Your number, with them",
  match_checkin: "How did it go?",
};

export function MessageCard({ card, busy = false, disabled = false, onAction }: Props) {
  const answered = card.actions.find((action) => action.id === card.answered) ?? null;
  const chips = card.kind === "match_checkin";
  return (
    <div className={`message-card is-${card.kind} ${answered ? "is-answered" : ""}`} role="group" aria-label={card.title || EYEBROWS[card.kind]}>
      <span className="message-card-eyebrow">{card.title || EYEBROWS[card.kind]}</span>
      {card.headline ? <strong className="message-card-headline">{card.headline}</strong> : null}
      {card.detail ? <span className="message-card-detail">{card.detail}</span> : null}
      {card.lines?.length ? (
        <ul className="message-card-lines">
          {card.lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      ) : null}
      {card.note ? <p className="message-card-note">{card.note}</p> : null}
      {answered ? (
        <p className="message-card-answered">You said: <strong>{answered.label}</strong></p>
      ) : (
        <div className={`message-card-actions ${chips ? "is-chips" : ""}`}>
          {card.actions.map((action) => (
            <button key={action.id} type="button" className={action.primary ? "is-primary" : ""} disabled={busy || disabled} onClick={() => onAction(action)}>{action.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}
