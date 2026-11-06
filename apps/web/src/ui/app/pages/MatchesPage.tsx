import { type FormEvent, useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, CalendarDays, Check, MessageCircle, MoreHorizontal, X } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import { deadlineLabel, initialOf, matchDayLabel, matchesLabel, needsList, poolLine, splitMatches, statusLine, type MatchCard, type MatchPool, type MatchReadiness, type PoolPair } from "../matches";

// Matches: where the user stands before match day, the one card to answer, who they are waiting
// on, the people they met, and their groups. Omi does the talking in the chat; this page is the
// record. Shapes: docs/matching-design.md section 6.

type Props = { onVibe: () => void; onChat: () => void; onContact: () => void };

const PASS_REASONS = [
  { id: "not_my_kind", label: "Not my kind of person" },
  { id: "reasons_off", label: "The reasons don't sound like me" },
  { id: "know_them", label: "I already know them" },
  { id: "not_now", label: "Not right now" },
];

export function MatchesPage({ onVibe, onChat, onContact }: Props) {
  const [readiness, setReadiness] = useState<MatchReadiness | null>(null);
  const [cards, setCards] = useState<MatchCard[]>([]);
  const [pools, setPools] = useState<MatchPool[]>([]);
  const [pairs, setPairs] = useState<PoolPair[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [answering, setAnswering] = useState<string | null>(null);
  const [passing, setPassing] = useState<MatchCard | null>(null);
  const [passReason, setPassReason] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [shownAgain, setShownAgain] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [joinNote, setJoinNote] = useState("");
  const joinRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [readinessRes, poolsRes, matchesRes] = await Promise.all([
        apiFetch("/api/me/match-readiness"),
        apiFetch("/api/me/pools"),
        apiFetch("/api/me/matches"),
      ]);
      if (cancelled) return;
      if (readinessRes.ok) setReadiness(await readinessRes.json());
      if (poolsRes.ok) {
        const data = await poolsRes.json();
        setPools(data.pools ?? []);
        setPairs(data.pairs ?? []);
      }
      // The card list is not built yet on the server; until it is, there are no cards.
      if (matchesRes.ok) setCards((await matchesRes.json()).matches ?? []);
      setLoaded(true);
    })().catch(() => { if (!cancelled) { setError("Could not load your matches."); setLoaded(true); } });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!menuId) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !(event.target instanceof Element && event.target.closest(".mt-row-menu"))) setMenuId(null);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, [menuId]);

  const ready = readiness?.ready ?? false;
  const split = splitMatches(cards);

  async function answer(card: MatchCard, decision: "accept" | "pass", note?: string) {
    if (answering) return;
    setAnswering(card.pair_id);
    setError("");
    const response = await apiFetch(`/api/me/matches/${card.pair_id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(note ? { answer: decision, note } : { answer: decision }),
    });
    setAnswering(null);
    if (!response.ok) {
      setError(await apiErrorMessage(response, "Could not send your answer."));
      return;
    }
    const data = await response.json();
    const updated: MatchCard = data.match ?? data;
    setCards((current) => current.map((item) => (item.pair_id === card.pair_id ? { ...item, ...updated } : item)));
    trackAppEvent("match_answered", { decision }, { page: "matches" });
    setPassing(null);
    setPassReason(null);
  }

  async function join(event: FormEvent) {
    event.preventDefault();
    const trimmed = code.trim().toUpperCase();
    if (!trimmed || joining) return;
    setJoining(true);
    setJoinNote("");
    const response = await apiFetch("/api/me/pools/join", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: trimmed }) });
    setJoining(false);
    if (!response.ok) {
      setJoinNote(await apiErrorMessage(response, "That code does not match any group."));
      return;
    }
    const data = await response.json();
    if (data.pool) setPools((current) => (current.some((pool) => pool.id === data.pool.id) ? current : [...current, data.pool]));
    setCode("");
    setJoinNote(`You're in ${data.pool?.name ?? "the group"}.`);
    trackAppEvent("pool_joined", {}, { page: "matches" });
  }

  const intro = (card: MatchCard, withActions: boolean) => (
    <article className="mt-card mt-intro" aria-label={`Introduction to ${card.name}`}>
      <div className="mt-person">
        <span className="mt-avatar" aria-hidden="true">{initialOf(card.name)}</span>
        <div>
          <h2>{card.name}</h2>
          {card.meet_line ? <p>{card.meet_line}</p> : null}
        </div>
      </div>
      {card.reasons.length ? (
        <div className="mt-section">
          <span className="mt-eyebrow">You'd click on</span>
          <ul className="mt-reasons">
            {card.reasons.map((reason) => (
              <li key={reason.area + reason.text}><span className="mt-dot is-done" aria-hidden="true"><Check /></span><span>{reason.text}</span></li>
            ))}
          </ul>
        </div>
      ) : null}
      {card.difference ? (
        <div className="mt-difference">
          <span className="mt-eyebrow">One difference, and that's fine</span>
          <p>{card.difference.text}</p>
        </div>
      ) : null}
      {card.icebreaker ? (
        <div className="mt-section">
          <span className="mt-eyebrow">An easy start</span>
          <p className="mt-starter">“{card.icebreaker}”</p>
        </div>
      ) : null}
      {withActions ? (
        <>
          <div className="mt-actions">
            <button type="button" className="secondary-button" disabled={answering === card.pair_id} onClick={() => { setPassing(card); setPassReason(null); }}>Not for me</button>
            <button type="button" disabled={answering === card.pair_id} onClick={() => void answer(card, "accept")}>{answering === card.pair_id ? "Sending..." : "Say hi"} <ArrowRight aria-hidden="true" size={16} /></button>
          </div>
          <p className="mt-fine">
            {card.name} sees a card like this about you. Nothing opens unless you both say hi.<br />
            {deadlineLabel(card.answer_by) ?? "Two days to answer"}. If either of you passes, the other only hears “not this week”.
          </p>
        </>
      ) : null}
    </article>
  );

  return (
    <section className="screen mt-screen">
      <header className="mt-head">
        <div>
          <h1>Matches</h1>
          <p>Omi introduces you to one person at a time, with a reason.</p>
        </div>
        {loaded ? <span className="mt-label">{matchesLabel(ready, split)}</span> : null}
      </header>

      {error ? <p className="mt-error" role="alert">{error}</p> : null}

      {loaded && readiness && !ready ? (
        <section className="mt-card" aria-labelledby="mt-needs-title">
          <h2 id="mt-needs-title">What Omi still needs</h2>
          <ul className="mt-needs">
            {needsList(readiness).map((item) => (
              <li key={item.id}>
                <span className={`mt-dot ${item.done ? "is-done" : ""}`} aria-hidden="true">{item.done ? <Check /> : null}</span>
                <span><strong>{item.label}</strong><small>{item.hint}</small></span>
              </li>
            ))}
          </ul>
          <p className="mt-note">No form for this. Omi will ask when it fits, or just tell it.</p>
          <div className="mt-actions">
            <button type="button" className="secondary-button" onClick={onVibe}>See your vibe</button>
            <button type="button" onClick={onChat}>Tell Omi now <ArrowRight aria-hidden="true" size={16} /></button>
          </div>
        </section>
      ) : null}

      {split.open.map((card) => intro(card, true))}

      {loaded && ready && !split.open.length ? (
        <section className="mt-looking" aria-label="Omi is looking">
          <span className="mt-eyebrow">Omi is looking</span>
          <p className="mt-big">Omi knows you well enough. <em>One person at a time,</em> when there's a real reason.</p>
          <p className="mt-note">You'll hear from Omi in your chat. No feed to refresh.</p>
        </section>
      ) : null}

      {split.waiting.map((card) => (
        <article className="mt-card" key={card.pair_id} aria-label={`Waiting for ${card.name}`}>
          <div className="mt-person">
            <span className="mt-avatar is-small" aria-hidden="true">{initialOf(card.name)}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h2 style={{ fontSize: 22 }}>{card.name}</h2>
              {card.pool_name ? <p>{card.pool_name}</p> : null}
            </div>
            <button type="button" className="mt-link is-strong" onClick={() => setShownAgain(shownAgain === card.pair_id ? null : card.pair_id)}>{shownAgain === card.pair_id ? "Hide the card" : "The card"}</button>
          </div>
          <div className="mt-wait"><div><strong>You said hi.</strong> Waiting for {card.name}. {card.answer_by ? <span>{deadlineLabel(card.answer_by)}.</span> : null}</div></div>
          <ol className="mt-steps">
            <li><span>01</span><span>If {card.name} says hi too, Omi tells you both in your own chats and suggests a time and place.</span></li>
            <li><span>02</span><span>If not, or there is no answer within two days, you hear “not this week” and nothing else. Never why.</span></li>
          </ol>
          {shownAgain === card.pair_id ? intro(card, false) : null}
        </article>
      ))}

      {split.people.length ? (
        <section className="mt-section" aria-labelledby="mt-people-title">
          <h2 id="mt-people-title">Your people</h2>
          <div className="mt-list">
            {split.people.map((card) => (
              <div key={card.pair_id}>
                <div className={`mt-row ${card.status === "no_show" ? "is-past" : ""}`}>
                  <span className={`mt-avatar is-small ${card.status === "introduced" ? "is-ink" : card.status === "no_show" ? "is-quiet" : ""}`} aria-hidden="true">{initialOf(card.name)}</span>
                  <div className="mt-row-copy"><strong>{card.name}</strong><span>{statusLine(card)}</span></div>
                  <div className="history-row-menu mt-row-menu">
                    <button className="history-menu-button" type="button" aria-haspopup="menu" aria-expanded={menuId === card.pair_id} aria-label={`More about ${card.name}`} onClick={() => setMenuId(menuId === card.pair_id ? null : card.pair_id)}><MoreHorizontal aria-hidden="true" /></button>
                    {menuId === card.pair_id ? (
                      <div className="history-menu" role="menu">
                        <button type="button" role="menuitem" onClick={() => { setMenuId(null); setShownAgain(shownAgain === card.pair_id ? null : card.pair_id); }}><MessageCircle aria-hidden="true" />{shownAgain === card.pair_id ? "Hide the introduction" : "See the introduction again"}</button>
                        {card.status === "introduced" ? <button type="button" role="menuitem" onClick={() => { setMenuId(null); onChat(); }}><CalendarDays aria-hidden="true" />Change the plan with Omi</button> : null}
                        {card.status === "introduced" ? <button type="button" role="menuitem" onClick={() => { setMenuId(null); onChat(); }}><X aria-hidden="true" />Call it off, kindly</button> : null}
                        <button type="button" role="menuitem" className="is-danger" onClick={() => { setMenuId(null); onContact(); }}><AlertTriangle aria-hidden="true" />Report or block {card.name}</button>
                      </div>
                    ) : null}
                  </div>
                </div>
                {shownAgain === card.pair_id ? <div style={{ padding: "0 12px 12px" }}>{intro(card, false)}</div> : null}
              </div>
            ))}
          </div>
          <p className="mt-note">Omi keeps this list. The talking happens wherever you two took it. Calling it off tells the other person only that it won't happen.</p>
        </section>
      ) : null}

      {loaded ? (
        <section className="mt-card" aria-labelledby="mt-join-title">
          <h2 id="mt-join-title">Join a group</h2>
          <p className="mt-note">A building, a batch, a club. Someone gave you a code? Omi looks inside that group first.</p>
          <form className="mt-join" onSubmit={(event) => void join(event)}>
            <label className="sr-only" htmlFor="mt-code">Group code</label>
            <input id="mt-code" ref={joinRef} value={code} onChange={(event) => setCode(event.target.value)} placeholder="6-letter code" maxLength={12} autoComplete="off" autoCapitalize="characters" />
            <button type="submit" disabled={joining || code.trim().length < 4}>{joining ? "Joining..." : "Join"}</button>
          </form>
          {joinNote ? <p className="mt-note" role="status">{joinNote}</p> : null}
          {pools.length ? (
            <div className="mt-list">
              {pools.map((pool) => {
                const line = poolLine(pool, pairs, cards);
                return (
                  <div className="mt-row" key={pool.id}>
                    <div className="mt-row-copy"><strong>{pool.name}</strong><span>Matches on {matchDayLabel(pool.match_weekday)}</span></div>
                    <span className={`mt-chip ${line.endsWith("intro") || line.endsWith("intros") ? "is-ink" : ""}`}>{line}</span>
                  </div>
                );
              })}
            </div>
          ) : null}
          <p className="mt-note">Groups see that you're in them, never your vibe.</p>
        </section>
      ) : null}

      {loaded && !ready ? (
        <section className="mt-section" aria-labelledby="mt-how-title">
          <h2 id="mt-how-title">How it goes</h2>
          <ol className="mt-how">
            <li><span>01</span><strong>One intro</strong><small>With the reason.</small></li>
            <li><span>02</span><strong>Both say hi</strong><small>Or nothing happens.</small></li>
            <li><span>03</span><strong>Omi hosts</strong><small>A plan, a nudge, a check-in.</small></li>
          </ol>
        </section>
      ) : null}

      {passing ? (
        <div className="confirm-overlay">
          <section className="confirm-dialog mt-pass" role="dialog" aria-modal="true" aria-labelledby="mt-pass-title" onKeyDown={(event) => { if (event.key === "Escape" && !answering) { setPassing(null); setPassReason(null); } }}>
            <div className="confirm-copy">
              <h2 id="mt-pass-title">Not for you. That's fine.</h2>
              <p>Tell Omi why, if you like. Only Omi sees it, and it picks better next time. {passing.name} is never told.</p>
            </div>
            <div className="mt-pass-reasons" role="group" aria-label="Why">
              {PASS_REASONS.map((reason) => (
                <button key={reason.id} type="button" className={passReason === reason.id ? "is-selected" : ""} aria-pressed={passReason === reason.id} onClick={() => setPassReason(passReason === reason.id ? null : reason.id)}>{reason.label}</button>
              ))}
              <button type="button" className={`is-report ${passReason === "report" ? "is-selected" : ""}`} aria-pressed={passReason === "report"} onClick={() => setPassReason(passReason === "report" ? null : "report")}>Something felt off, report this</button>
            </div>
            <div className="confirm-actions">
              <button type="button" className="secondary-button" disabled={Boolean(answering)} onClick={() => { setPassing(null); setPassReason(null); }}>Back</button>
              <button type="button" disabled={Boolean(answering)} onClick={() => { if (passReason === "report") onContact(); void answer(passing, "pass", passReason ?? undefined); }}>{answering ? "Sending..." : passReason ? "Done" : "Done, no reason"}</button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
