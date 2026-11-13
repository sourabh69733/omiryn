import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import type { EmojiClickData, EmojiStyle, Theme } from "emoji-picker-react";
import { AlertTriangle, Ban, Check, ImagePlus, Lock, Menu, MoreHorizontal, Smile, SmilePlus, Sparkles, X } from "lucide-react";
import { apiFetch } from "../../../lib/api";
import { ReportDialog } from "../ReportDialog";
import { StateView } from "../StateView";
import { initialOf, type MatchCard } from "../matches";
import { IMAGE_TYPES, MATCH_EVENT, QUICK_REACTIONS, RESIZE_ABOVE_BYTES, UPLOAD_MAX_BYTES, clusterClass, dayLabel, imageProblem, isBigEmoji, mergeMessages, newestId, startsDay, type MatchEventDetail, type PersonImage, type PersonMessage } from "../people";

const EmojiPicker = lazy(() => import("emoji-picker-react"));
const MESSAGE_MAX_LENGTH = 2000;
const CAPTION_MAX_LENGTH = 500;
// "Typing" is sent again while the user keeps writing, and the other side forgets it by itself.
const TYPING_EVERY_MS = 2500;
const TYPING_SHOWN_MS = 6000;

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

// Pictures are private to the two people, so they are fetched with the session and shown from memory.
const pictureUrls = new Map<string, Promise<string>>();
function pictureUrl(pairId: string, image: PersonImage): Promise<string> {
  const key = `${pairId}:${image.id}`;
  let url = pictureUrls.get(key);
  if (!url) {
    url = apiFetch(`/api/me/matches/${pairId}/media/${image.id}`).then(async (response) => {
      if (!response.ok) throw new Error("no picture");
      return URL.createObjectURL(await response.blob());
    });
    url.catch(() => pictureUrls.delete(key));
    pictureUrls.set(key, url);
  }
  return url;
}

/** A still picture above the mark is drawn smaller before it is sent; a GIF goes as it is. */
async function readyToSend(file: Blob): Promise<Blob> {
  if (file.type === "image/gif" || file.size <= RESIZE_ABOVE_BYTES) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const smaller = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.88));
    return smaller && smaller.size < file.size ? smaller : file;
  } catch {
    return file;
  }
}

function Picture({ pairId, image, localUrl, onOpen }: { pairId: string; image?: PersonImage | null; localUrl?: string; onOpen: (url: string) => void }) {
  const [url, setUrl] = useState(localUrl ?? "");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (localUrl || !image) return;
    let cancelled = false;
    pictureUrl(pairId, image).then((value) => { if (!cancelled) setUrl(value); }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [pairId, image?.id, localUrl]);
  const ratio = image?.width && image?.height ? `${image.width} / ${image.height}` : undefined;
  if (failed) return <div className="pc-picture is-missing">Picture could not be loaded</div>;
  return (
    <button type="button" className="pc-picture" style={{ aspectRatio: ratio }} disabled={!url} onClick={() => url && onOpen(url)} aria-label="Open picture">
      {url ? <img src={url} alt={image?.content_type === "image/gif" ? "GIF" : "Picture"} /> : null}
    </button>
  );
}

/* The chat between the user and one person Omi introduced. Only the two of them can read it; Omi
   stays out. Messages come from the server (docs/api-contract.md); the socket only says that
   something happened, and this screen fetches it. */
export function PersonChatPage({ pairId, card, cardsLoaded, userAvatar, isMobile, onOpenNavigation, onChanged, onMatches }: Props) {
  const [messages, setMessages] = useState<PersonMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [open, setOpen] = useState(true);
  const [draft, setDraft] = useState("");
  const [picked, setPicked] = useState<{ file: Blob; url: string } | null>(null);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [reactFor, setReactFor] = useState<number | null>(null);
  const [theirTyping, setTheirTyping] = useState(false);
  const [viewing, setViewing] = useState("");
  const [showWhy, setShowWhy] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const messagesRef = useRef<PersonMessage[]>([]);
  const stickRef = useRef(true);
  // Distance from the bottom to hold while earlier messages are added above.
  const anchorRef = useRef<number | null>(null);
  const typingSentRef = useRef(0);
  const typingTimerRef = useRef<number | null>(null);
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
      if (data.messages.some((message: PersonMessage) => !message.mine)) {
        setTheirTyping(false);
        void markRead();
      }
    }
  }, [pairId, markRead]);

  // One message again, after someone put an emoji on it.
  const refreshMessage = useCallback(async (messageId: number) => {
    const response = await apiFetch(`/api/me/matches/${pairId}/messages?before=${messageId + 1}&limit=1`).catch(() => null);
    if (!response?.ok) return;
    const data = await response.json();
    setMessages((current) => mergeMessages(current, data.messages));
  }, [pairId]);

  const sayTyping = useCallback((active: boolean) => {
    if (!active && !typingSentRef.current) return;
    if (active && Date.now() - typingSentRef.current < TYPING_EVERY_MS) return;
    typingSentRef.current = active ? Date.now() : 0;
    void apiFetch(`/api/me/matches/${pairId}/typing`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active }) }).catch(() => undefined);
  }, [pairId]);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setLoading(true);
    setMissing(false);
    setError("");
    setDraft("");
    setPicked(null);
    setShowWhy(false);
    setTheirTyping(false);
    setReactFor(null);
    setEmojiOpen(false);
    stickRef.current = true;
    typingSentRef.current = 0;
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
      if (detail.type === "match.typing") {
        const active = detail.payload.active !== false;
        setTheirTyping(active);
        if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current);
        typingTimerRef.current = active ? window.setTimeout(() => setTheirTyping(false), TYPING_SHOWN_MS) : null;
        return;
      }
      if (detail.type === "match.reaction" && typeof detail.payload.message_id === "number") {
        void refreshMessage(detail.payload.message_id);
        return;
      }
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
      if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current);
    };
  }, [pairId, catchUp, refreshMessage]);

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
  }, [messages, loading, showWhy, theirTyping]);

  // Menus and pickers close on a click elsewhere or Escape.
  useEffect(() => {
    if (!menuOpen && !emojiOpen && reactFor === null && !viewing) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key !== "Escape") return;
      } else if (event.target instanceof Element && event.target.closest(".pc-menu, .emoji-picker-anchor, .pc-react, .pc-viewer img")) {
        return;
      }
      setMenuOpen(false);
      setEmojiOpen(false);
      setReactFor(null);
      setViewing("");
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menuOpen, emojiOpen, reactFor, viewing]);

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

  async function send(text: string, clientId: string, picture?: Blob) {
    const response = picture
      ? await readyToSend(picture).then((body) => apiFetch(`/api/me/matches/${pairId}/images?client_id=${encodeURIComponent(clientId)}&caption=${encodeURIComponent(text)}`, { method: "POST", headers: { "Content-Type": body.type || "application/octet-stream" }, body })).catch(() => null)
      : await apiFetch(`/api/me/matches/${pairId}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, client_id: clientId }) }).catch(() => null);
    if (response?.ok) {
      const data = await response.json();
      setMessages((current) => mergeMessages(current, [data.message]));
      onChanged();
      return;
    }
    setMessages((current) => current.map((message) => (message.client_id === clientId && message.pending ? { ...message, failed: true } : message)));
    if (response?.status === 409) {
      setOpen(false);
      setError("This chat is closed, so that was not sent.");
      onChanged();
    } else if (response?.status === 429) {
      setError("That is a lot in one minute. Wait a moment, then send again.");
    } else if (response?.status === 413 || response?.status === 415) {
      const detail = await response.json().then((data) => String(data.detail || "")).catch(() => "");
      setError(detail || "That picture could not be sent.");
    } else {
      setError("Could not send. Check your connection and try again.");
    }
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if ((!text && !picked) || !open) return;
    const clientId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    setError("");
    setDraft("");
    setEmojiOpen(false);
    stickRef.current = true;
    sayTyping(false);
    setMessages((current) => [...current, { id: -Date.now(), mine: true, text: picked ? text.slice(0, CAPTION_MAX_LENGTH) : text, created_at: new Date().toISOString(), client_id: clientId, pending: true, localImage: picked }]);
    void send(picked ? text.slice(0, CAPTION_MAX_LENGTH) : text, clientId, picked?.file);
    setPicked(null);
    inputRef.current?.focus();
  }

  function retry(message: PersonMessage) {
    if (!message.client_id) return;
    setError("");
    setMessages((current) => current.map((item) => (item.client_id === message.client_id ? { ...item, failed: false } : item)));
    void send(message.text, message.client_id, message.localImage?.file);
  }

  function pick(file: Blob | null | undefined) {
    if (!file) return;
    const problem = imageProblem(file) || (file.size > UPLOAD_MAX_BYTES * 3 ? "That picture is too big." : "");
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    setPicked({ file, url: URL.createObjectURL(file) });
    inputRef.current?.focus();
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const file = [...event.clipboardData.files].find((item) => IMAGE_TYPES.includes(item.type));
    if (!file) return;
    event.preventDefault();
    pick(file);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends on a keyboard; on a phone it is a new line and the button sends.
    if (event.key === "Enter" && !event.shiftKey && !isMobile && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  function insertEmoji(data: EmojiClickData) {
    const input = inputRef.current;
    const start = input?.selectionStart ?? draft.length;
    const end = input?.selectionEnd ?? draft.length;
    const next = `${draft.slice(0, start)}${data.emoji}${draft.slice(end)}`.slice(0, MESSAGE_MAX_LENGTH);
    setDraft(next);
    window.requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(start + data.emoji.length, start + data.emoji.length);
    });
  }

  async function react(message: PersonMessage, emoji: string | null) {
    setReactFor(null);
    const before = message.reactions ?? { mine: null, theirs: null };
    // Shown at once; the server's answer (or the old value, if it failed) replaces it.
    setMessages((current) => current.map((item) => (item.id === message.id ? { ...item, reactions: { ...before, mine: emoji } } : item)));
    const response = await apiFetch(`/api/me/matches/${pairId}/messages/${message.id}/reaction`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ emoji }) }).catch(() => null);
    if (response?.ok) {
      const data = await response.json();
      if (data.message) setMessages((current) => mergeMessages(current, [data.message]));
    } else {
      setMessages((current) => current.map((item) => (item.id === message.id ? { ...item, reactions: before } : item)));
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
  // Only what Omi actually said: a pair with no written reasons shows no card, never a filler line.
  const hasWhy = reasons.length > 0;
  const why = (
    <section className="pc-why" aria-label={`Why Omi introduced you to ${name}`}>
      <p className="pc-why-title"><Sparkles aria-hidden="true" />Why Omi introduced you</p>
      <ul>{reasons.map((reason) => <li key={reason.text}>{reason.text}</li>)}</ul>
      {card?.difference ? <p className="pc-why-line"><strong>One difference:</strong> {card.difference.text}</p> : null}
      {card?.icebreaker ? <p className="pc-why-line"><strong>An easy start:</strong> {card.icebreaker}</p> : null}
    </section>
  );
  const lastIsTheirs = messages.length > 0 && !messages[messages.length - 1].mine;

  return (
    <section className="screen interview-screen legacy-chat-screen pc-screen">
      <div className="chat-workspace">
        <section className="chat-card agentic-chat">
          <div className="card-heading">
            {onOpenNavigation ? <button type="button" className="omi-back" onClick={onOpenNavigation} aria-label="Open navigation"><Menu aria-hidden="true" /></button> : null}
            <div className="chat-title-lockup">
              <span className="pc-avatar" aria-hidden="true">{initialOf(name)}</span>
              <div><h2>{name}</h2><small className={theirTyping ? "is-typing" : ""}>{theirTyping ? "typing…" : "Introduced by Omi"}</small></div>
            </div>
            <div className="chat-controls omi-chat-menu pc-menu">
              <button type="button" className="omi-menu-button" aria-haspopup="menu" aria-expanded={menuOpen} aria-label={`More about ${name}`} onClick={() => setMenuOpen((value) => !value)}><MoreHorizontal aria-hidden="true" /></button>
              {menuOpen ? (
                <div className="history-menu pc-menu-list" role="menu">
                  {hasWhy ? <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); stickRef.current = false; setShowWhy((value) => !value); if (logRef.current) logRef.current.scrollTop = 0; }}><Sparkles aria-hidden="true" />{showWhy ? "Hide the introduction" : "Why Omi introduced you"}</button> : null}
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
            {!loading && hasWhy && (showWhy || !messages.length) ? why : null}
            {messages.map((message, index) => {
              const cluster = clusterClass(messages, index);
              const showAvatar = cluster === "cluster-single" || cluster.startsWith("cluster-end");
              const side = message.mine ? "user" : "agent";
              const picture = message.image || message.localImage;
              const bigEmoji = !picture && isBigEmoji(message.text);
              const reactions = message.reactions;
              const hasReaction = Boolean(reactions?.mine || reactions?.theirs);
              const canReact = open && !message.pending && !message.failed;
              return (
                <div key={message.id}>
                  {startsDay(messages, index) ? <div className="chat-day-separator" role="separator"><span>{dayLabel(message.created_at)}</span></div> : null}
                  <div className={`message-row ${side} ${cluster} ${message.pending ? "is-pending" : ""} ${hasReaction ? "has-reaction" : ""} ${reactFor === message.id ? "is-reacting" : ""}`}>
                    {!message.mine ? showAvatar ? <span className="chat-avatar agent pc-bubble-avatar" aria-hidden="true">{initialOf(name)}</span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                    <div className={`message ${side} ${picture ? "pc-has-picture" : ""} ${bigEmoji ? "pc-big-emoji" : ""}`}>
                      {picture ? <Picture pairId={pairId} image={message.image} localUrl={message.localImage?.url} onOpen={setViewing} /> : null}
                      {message.text ? <div className={`message-content ${side}`}>{message.text}</div> : null}
                      {hasReaction ? (
                        <span className="pc-reactions">
                          {reactions?.theirs ? <span className="pc-reaction" role="img" aria-label={`${name} reacted ${reactions.theirs}`}>{reactions.theirs}</span> : null}
                          {reactions?.mine ? <button type="button" className="pc-reaction is-yours" disabled={!canReact} aria-label={`Remove your reaction ${reactions.mine}`} onClick={() => void react(message, null)}>{reactions.mine}</button> : null}
                        </span>
                      ) : null}
                      {canReact ? (
                        <span className="pc-react">
                          <button type="button" className="pc-react-button" aria-label="React" aria-expanded={reactFor === message.id} onClick={() => setReactFor(reactFor === message.id ? null : message.id)}><SmilePlus aria-hidden="true" /></button>
                          {reactFor === message.id ? (
                            <span className="pc-react-row" role="group" aria-label="React">
                              {QUICK_REACTIONS.map((emoji) => <button type="button" key={emoji} className={reactions?.mine === emoji ? "is-selected" : ""} onClick={() => void react(message, reactions?.mine === emoji ? null : emoji)}>{emoji}</button>)}
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                    </div>
                    {message.mine ? showAvatar ? <span className="chat-avatar user">{userAvatar}</span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                  </div>
                  {message.failed ? <div className="message-status-row" role="status"><span className="message-status-text">Not sent</span>{open ? <button type="button" className="message-retry-button" onClick={() => retry(message)}>Retry</button> : null}</div> : null}
                </div>
              );
            })}
            {theirTyping ? (
              <div className={`message-row agent is-new ${lastIsTheirs ? "cluster-end same-cluster" : "cluster-single"}`} aria-label={`${name} is typing`}>
                <span className="chat-avatar agent pc-bubble-avatar" aria-hidden="true">{initialOf(name)}</span>
                <div className="message agent typing-message"><div className="message-content typing-content"><span className="typing-dots"><span /><span /><span /></span></div></div>
              </div>
            ) : null}
          </div>
          {error ? <p className="pc-error" role="alert">{error}</p> : null}
          {open ? (
            <>
            {picked ? (
              <div className="pc-picked" role="status">
                <img src={picked.url} alt="The picture you are about to send" />
                <span>{picked.file.type === "image/gif" ? "GIF" : "Picture"} ready. Add a line if you like.</span>
                <button type="button" onClick={() => setPicked(null)} aria-label="Remove the picture"><X aria-hidden="true" /></button>
              </div>
            ) : null}
            <form className="composer pc-composer" onSubmit={submit}>
              <div className="composer-tools">
                <input ref={fileRef} type="file" accept={IMAGE_TYPES.join(",")} hidden onChange={(event) => { pick(event.target.files?.[0]); event.target.value = ""; }} />
                <button type="button" className="chat-upload-button" aria-label="Send a picture or GIF" title="Send a picture or GIF" onClick={() => fileRef.current?.click()}><ImagePlus aria-hidden="true" /></button>
                <div className="emoji-picker-anchor">
                  <button className="emoji-trigger-button" type="button" aria-label="Add emoji" aria-expanded={emojiOpen} onClick={() => setEmojiOpen((value) => !value)}><Smile className="emoji-trigger-icon" aria-hidden="true" /></button>
                  {emojiOpen ? (
                    <div className="emoji-picker-popover">
                      <Suspense fallback={<div className="emoji-picker-loading">Loading emoji...</div>}>
                        <EmojiPicker height={360} emojiStyle={"native" as EmojiStyle} lazyLoadEmojis previewConfig={{ showPreview: false }} searchPlaceHolder="Search emoji" skinTonesDisabled theme={"light" as Theme} width="100%" onEmojiClick={insertEmoji} />
                      </Suspense>
                    </div>
                  ) : null}
                </div>
              </div>
              <textarea ref={inputRef} value={draft} maxLength={picked ? CAPTION_MAX_LENGTH : MESSAGE_MAX_LENGTH} rows={1} onChange={(event) => { setDraft(event.target.value); sayTyping(Boolean(event.target.value.trim())); }} onBlur={() => sayTyping(false)} onKeyDown={onKeyDown} onPaste={onPaste} placeholder={picked ? "Add a line (optional)" : `Message ${name}`} aria-label={`Message ${name}`} />
              {draft.length >= MESSAGE_MAX_LENGTH - 200 ? <span className="chat-character-count" aria-live="polite">{draft.length}/{MESSAGE_MAX_LENGTH}</span> : null}
              <button type="submit" disabled={!draft.trim() && !picked} aria-label="Send message" onPointerDown={(event) => { if (!event.currentTarget.disabled) event.preventDefault(); }}><svg className="send-message-icon" viewBox="0 0 24 24"><path d="M4 20 21 12 4 4l3.3 7.2L15 12l-7.7.8L4 20Z" /></svg></button>
            </form>
            </>
          ) : !loading ? (
            <div className="omi-readonly-bar" role="status">
              <span>This chat is closed. You can still read it.</span>
              <button type="button" onClick={onMatches}>Matches</button>
            </div>
          ) : null}
        </section>
      </div>
      {viewing ? (
        <div className="confirm-overlay pc-viewer" role="dialog" aria-modal="true" aria-label="Picture">
          <img src={viewing} alt="Picture, full size" />
          <button type="button" className="pc-viewer-close" onClick={() => setViewing("")} aria-label="Close picture"><X aria-hidden="true" /></button>
        </div>
      ) : null}
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
