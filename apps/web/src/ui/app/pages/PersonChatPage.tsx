import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { AlertTriangle, Ban, Check, Lock, Menu, MoreHorizontal, Sparkles, X } from "lucide-react";
import { apiFetch } from "../../../lib/api";
import { ReportDialog } from "../ReportDialog";
import { StateView } from "../StateView";
import { initialOf, type MatchCard } from "../matches";
import { MATCH_EVENT, clusterClass, dayLabel, mergeMessages, newestId, startsDay, type MatchEventDetail, type PersonMessage } from "../people";

const MESSAGE_MAX_LENGTH = 2000;

type Props = {
  pairId: string;
  /** The person's card, once the shell has loaded it; null while loading or when there is no such chat. */
  card: MatchCard | null;
  /** True once the shell has asked for the cards, so a missing card means "no such chat". */
  cardsLoaded: boolean;
  userAvatar: ReactNode;
  isMobile: boolean;
  onOpenNavigation?: () => void;
  /** The chat list should refetch: something was read, sent, blocked or reported. */
  onChanged: () => void;
  onMatches: () => void;
};

/* The chat between the user and one person Omi introduced. Only the two of them can read it; Omi
   stays out. Messages come from the server (docs/api-contract.md); the socket only says that one
   arrived, and this screen fetches it. */
export function PersonChatPage({ pairId, card, cardsLoaded, userAvatar, isMobile, onOpenNavigation, onChanged, onMatches }: Props) {
  const [messages, setMessages] = useState<PersonMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [open, setOpen] = useState(true);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [showWhy, setShowWhy] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<PersonMessage[]>([]);
  const stickRef = useRef(true);
  // Distance from the bottom to hold while earlier messages are added above.
  const anchorRef = useRef<number | null>(null);
  messagesRef.current = messages;
  const name = card?.name || "this person";

  const markRead = useCallback(async () => {
    if (document.visibilityState !== "visible") return;
    const response = await apiFetch(`/api/me/matches/${pairId}/read`, { method: "POST" }).catch(() => null);
    if (response?.ok) onChanged();
  }, [pairId, onChanged]);

  // Everything after the newest message on screen: after a socket event, a reconnect or coming back to the tab.
  const catchUp = useCallback(async () => {
    const response = await apiFetch(`/api/me/matches/${pairId}/messages?after=${newestId(messagesRef.current)}`).catch(() => null);
    if (!response?.ok) return;
    const data = await response.json();
    setOpen(Boolean(data.chat?.open));
    if (data.messages.length) {
      setMessages((current) => mergeMessages(current, data.messages));
      if (data.messages.some((message: PersonMessage) => !message.mine)) void markRead();
    }
  }, [pairId, markRead]);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setLoading(true);
    setMissing(false);
    setError("");
    setDraft("");
    setShowWhy(false);
    stickRef.current = true;
    apiFetch(`/api/me/matches/${pairId}/messages`)
      .then(async (response) => {
        if (cancelled) return;
        if (!response.ok) {
          setMissing(true);
          return;
        }
        const data = await response.json();
        if (cancelled) return;
        setMessages(data.messages);
        setHasMore(Boolean(data.has_more));
        setOpen(Boolean(data.chat?.open));
        if (data.chat?.unread) void markRead();
      })
      .catch(() => { if (!cancelled) setMissing(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [pairId]);

  useEffect(() => {
    const onEvent = (event: Event) => {
      const detail = (event as CustomEvent<MatchEventDetail>).detail;
      if (detail?.payload?.pair_id !== pairId) return;
      void catchUp();
    };
    const onVisible = () => { if (document.visibilityState === "visible") void catchUp(); };
    window.addEventListener(MATCH_EVENT, onEvent);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      window.removeEventListener(MATCH_EVENT, onEvent);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [pairId, catchUp]);

  // Stay at the newest message unless the user scrolled up to read; after loading earlier
  // messages, keep the one they were reading where it was.
  useLayoutEffect(() => {
    const log = logRef.current;
    if (!log) return;
    if (anchorRef.current !== null) {
      log.scrollTop = log.scrollHeight - anchorRef.current;
      anchorRef.current = null;
    } else if (stickRef.current) {
      log.scrollTop = log.scrollHeight;
    }
  }, [messages, loading, showWhy]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !(event.target instanceof Element && event.target.closest(".pc-menu"))) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menuOpen]);

  // The confirmation goes by itself, like the one on the Matches page.
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 7000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function loadEarlier() {
    const first = messages.find((message) => !message.pending);
    if (!first || busy) return;
    setBusy(true);
    const response = await apiFetch(`/api/me/matches/${pairId}/messages?before=${first.id}`).catch(() => null);
    setBusy(false);
    if (!response?.ok) return;
    const data = await response.json();
    stickRef.current = false;
    const log = logRef.current;
    anchorRef.current = log ? log.scrollHeight - log.scrollTop : null;
    setMessages((current) => mergeMessages(current, data.messages));
    setHasMore(Boolean(data.has_more));
  }

  async function send(text: string, clientId: string) {
    const response = await apiFetch(`/api/me/matches/${pairId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, client_id: clientId }),
    }).catch(() => null);
    if (response?.ok) {
      const data = await response.json();
      setMessages((current) => mergeMessages(current, [data.message]));
      onChanged();
      return;
    }
    setMessages((current) => current.map((message) => (message.client_id === clientId && message.pending ? { ...message, failed: true } : message)));
    if (response?.status === 409) {
      setOpen(false);
      setError("This chat is closed, so that message was not sent.");
      onChanged();
    } else if (response?.status === 429) {
      setError("That is a lot of messages in one minute. Wait a moment, then send again.");
    } else {
      setError("Could not send. Check your connection and try again.");
    }
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || !open) return;
    const clientId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    setError("");
    setDraft("");
    stickRef.current = true;
    setMessages((current) => [...current, { id: -Date.now(), mine: true, text, created_at: new Date().toISOString(), client_id: clientId, pending: true }]);
    void send(text, clientId);
    inputRef.current?.focus();
  }

  function retry(message: PersonMessage) {
    if (!message.client_id) return;
    setError("");
    setMessages((current) => current.map((item) => (item.client_id === message.client_id ? { ...item, failed: false } : item)));
    void send(message.text, message.client_id);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends on a keyboard; on a phone it is a new line and the button sends.
    if (event.key === "Enter" && !event.shiftKey && !isMobile && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  async function block() {
    setBusy(true);
    const response = await apiFetch(`/api/me/matches/${pairId}/block`, { method: "POST" }).catch(() => null);
    setBusy(false);
    setBlocking(false);
    if (!response?.ok) {
      setError("Could not block. Nothing changed; try again, or tell us through Contact.");
      return;
    }
    setOpen(false);
    setToast(`Blocked. ${name} won't come up again.`);
    onChanged();
  }

  if (missing || (cardsLoaded && !card && !loading && !messages.length)) {
    return (
      <section className="screen interview-screen legacy-chat-screen">
        <div className="chat-workspace">
          <section className="chat-card agentic-chat conversation-empty">
            <div className="card-heading">
              {onOpenNavigation ? <button type="button" className="omi-back" onClick={onOpenNavigation} aria-label="Open navigation"><Menu aria-hidden="true" /></button> : null}
              <div className="chat-title-lockup"><div><h2>Chat</h2></div></div>
            </div>
            <div className="chat-log">
              <StateView kind="empty" title="This chat isn't here" detail="It may have ended, or it belongs to another account."><button type="button" onClick={onMatches}>Go to Matches</button></StateView>
            </div>
          </section>
        </div>
      </section>
    );
  }

  const reasons = card?.reasons ?? [];
  const why = (
    <section className="pc-why" aria-label={`Why Omi introduced you to ${name}`}>
      <p className="pc-why-title"><Sparkles aria-hidden="true" />Why Omi introduced you</p>
      {reasons.length ? <ul>{reasons.map((reason) => <li key={reason.text}>{reason.text}</li>)}</ul> : <p>Omi thought you two would get along.</p>}
      {card?.difference ? <p className="pc-why-line"><strong>One difference:</strong> {card.difference.text}</p> : null}
      {card?.icebreaker ? <p className="pc-why-line"><strong>An easy start:</strong> {card.icebreaker}</p> : null}
    </section>
  );

  return (
    <section className="screen interview-screen legacy-chat-screen pc-screen">
      <div className="chat-workspace">
        <section className="chat-card agentic-chat">
          <div className="card-heading">
            {onOpenNavigation ? <button type="button" className="omi-back" onClick={onOpenNavigation} aria-label="Open navigation"><Menu aria-hidden="true" /></button> : null}
            <div className="chat-title-lockup">
              <span className="pc-avatar" aria-hidden="true">{initialOf(name)}</span>
              <div><h2>{name}</h2><small>Introduced by Omi</small></div>
            </div>
            <div className="chat-controls omi-chat-menu pc-menu">
              <button type="button" className="omi-menu-button" aria-haspopup="menu" aria-expanded={menuOpen} aria-label={`More about ${name}`} onClick={() => setMenuOpen((value) => !value)}><MoreHorizontal aria-hidden="true" /></button>
              {menuOpen ? (
                <div className="history-menu pc-menu-list" role="menu">
                  <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); stickRef.current = false; setShowWhy((value) => !value); if (logRef.current) logRef.current.scrollTop = 0; }}><Sparkles aria-hidden="true" />{showWhy ? "Hide the introduction" : "Why Omi introduced you"}</button>
                  {card?.status !== "blocked" ? <button type="button" role="menuitem" className="is-danger" onClick={() => { setMenuOpen(false); setBlocking(true); }}><Ban aria-hidden="true" />Block {name}</button> : null}
                  {card ? <button type="button" role="menuitem" className="is-danger" onClick={() => { setMenuOpen(false); setReporting(true); }}><AlertTriangle aria-hidden="true" />Report {name}</button> : null}
                </div>
              ) : null}
            </div>
          </div>
          <div className="chat-log" ref={logRef} aria-live="polite" onScroll={(event) => { const log = event.currentTarget; stickRef.current = log.scrollHeight - log.scrollTop - log.clientHeight < 80; }}>
            {loading ? <StateView kind="loading" title="Opening your chat…" /> : null}
            {!loading && hasMore ? <button type="button" className="pc-earlier" disabled={busy} onClick={() => void loadEarlier()}>{busy ? "Loading…" : "Earlier messages"}</button> : null}
            {!loading ? <p className="omi-chat-notice"><Lock aria-hidden="true" />Only you and {name} can read this chat. Omi can't.</p> : null}
            {!loading && (showWhy || !messages.length) ? why : null}
            {messages.map((message, index) => {
              const cluster = clusterClass(messages, index);
              const showAvatar = cluster === "cluster-single" || cluster.startsWith("cluster-end");
              return (
                <div key={message.id}>
                  {startsDay(messages, index) ? <div className="chat-day-separator" role="separator"><span>{dayLabel(message.created_at)}</span></div> : null}
                  <div className={`message-row ${message.mine ? "user" : "agent"} ${cluster} ${message.pending ? "is-pending" : ""}`}>
                    {!message.mine ? showAvatar ? <span className="chat-avatar agent pc-bubble-avatar" aria-hidden="true">{initialOf(name)}</span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                    <div className={`message ${message.mine ? "user" : "agent"}`}>
                      <div className={`message-content ${message.mine ? "user" : "agent"}`}>{message.text}</div>
                    </div>
                    {message.mine ? showAvatar ? <span className="chat-avatar user">{userAvatar}</span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                  </div>
                  {message.failed ? <div className="message-status-row" role="status"><span className="message-status-text">Not sent</span>{open ? <button type="button" className="message-retry-button" onClick={() => retry(message)}>Retry</button> : null}</div> : null}
                </div>
              );
            })}
          </div>
          {error ? <p className="pc-error" role="alert">{error}</p> : null}
          {open ? (
            <form className="composer pc-composer" onSubmit={submit}>
              <textarea ref={inputRef} value={draft} maxLength={MESSAGE_MAX_LENGTH} rows={1} onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} placeholder={`Message ${name}`} aria-label={`Message ${name}`} />
              {draft.length >= MESSAGE_MAX_LENGTH - 200 ? <span className="chat-character-count" aria-live="polite">{draft.length}/{MESSAGE_MAX_LENGTH}</span> : null}
              <button type="submit" disabled={!draft.trim()} aria-label="Send message" onPointerDown={(event) => { if (!event.currentTarget.disabled) event.preventDefault(); }}><svg className="send-message-icon" viewBox="0 0 24 24"><path d="M4 20 21 12 4 4l3.3 7.2L15 12l-7.7.8L4 20Z" /></svg></button>
            </form>
          ) : !loading ? (
            <div className="omi-readonly-bar" role="status">
              <span>This chat is closed. You can still read it.</span>
              <button type="button" onClick={onMatches}>Matches</button>
            </div>
          ) : null}
        </section>
      </div>
      {blocking ? (
        <div className="confirm-overlay">
          <section className="confirm-dialog mt-pass" role="dialog" aria-modal="true" aria-labelledby="pc-block-title" onKeyDown={(event) => { if (event.key === "Escape" && !busy) setBlocking(false); }}>
            <div className="confirm-copy">
              <h2 id="pc-block-title">Block {name}?</h2>
              <p>The chat closes for both of you and you won't be matched again. {name} is not told why.</p>
            </div>
            <div className="confirm-actions">
              <button type="button" className="secondary-button" disabled={busy} onClick={() => setBlocking(false)}>Back</button>
              <button type="button" className="danger-button" disabled={busy} onClick={() => void block()}>{busy ? "Blocking..." : "Block"}</button>
            </div>
          </section>
        </div>
      ) : null}
      {reporting && card ? (
        <ReportDialog card={card} page="person" onClose={() => setReporting(false)} onDone={(_updated, message) => { setReporting(false); setOpen(false); setToast(message); onChanged(); }} />
      ) : null}
      {toast ? (
        <div className="mt-toast" role="status">
          <Check aria-hidden="true" />
          <span>{toast}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setToast("")}><X aria-hidden="true" /></button>
        </div>
      ) : null}
    </section>
  );
}
