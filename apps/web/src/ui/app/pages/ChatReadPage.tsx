// The read of one uploaded chat (/read/<upload id>): the numbers code counted for both people,
// what Omi wrote about the two of them, and a picture to share. Made on the first visit.
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, RefreshCw, Share2 } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { type ChatRead, dateRange, dayText, drawReadCard, sideFacts, versus } from "../chatRead";

type Props = {
  sourceId: string;
  onBack: () => void;
};

type Ready = Extract<ChatRead, { state: "ready" }>;

const WHY_NOT: Record<string, { title: string; detail: string }> = {
  group_chat: { title: "This one is a group chat", detail: "The read works on a chat between two people. Share a one-to-one chat from 📎 in chat." },
  too_short: { title: "Too little to read", detail: "Both of you need at least ten messages in the chat for a read." },
  no_chat: { title: "Nothing to read here", detail: "This upload is notes, not a chat between two people." },
};

export function ChatReadPage({ sourceId, onBack }: Props) {
  const [read, setRead] = useState<ChatRead | null>(null);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState("");
  const [shared, setShared] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    setRead(null);
    setError("");
    (async () => {
      const response = await apiFetch(`/api/me/context-sources/${sourceId}/chat-read`);
      if (cancelled) return;
      if (!response.ok) {
        setError(response.status === 404 ? "This upload is gone." : await apiErrorMessage(response, "Could not load the read."));
        return;
      }
      const stored: ChatRead = await response.json();
      if (stored.state !== "none") {
        setRead(stored);
        return;
      }
      await make(false, () => cancelled);
    })().catch(() => { if (!cancelled) setError("Could not load the read."); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);

  async function make(again: boolean, cancelled: () => boolean = () => false) {
    setMaking(true);
    setError("");
    const response = await apiFetch(`/api/me/context-sources/${sourceId}/chat-read${again ? "?again=true" : ""}`, { method: "POST" }).catch(() => null);
    if (cancelled()) return;
    setMaking(false);
    if (!response?.ok) {
      setError(response ? await apiErrorMessage(response, "Could not read this chat. Try again.") : "Could not read this chat. Try again.");
      return;
    }
    setRead(await response.json());
  }

  useEffect(() => {
    if (!shared) return;
    const timer = window.setTimeout(() => setShared(""), 5000);
    return () => window.clearTimeout(timer);
  }, [shared]);

  async function share(ready: Ready) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    // The picture uses the page's own fonts; wait for them or the first draw falls back.
    await document.fonts?.ready;
    drawReadCard(canvas, ready);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) {
      setError("Could not make the picture.");
      return;
    }
    const file = new File([blob], `omiryn-read-${ready.them.toLowerCase()}.png`, { type: "image/png" });
    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: `${ready.me} & ${ready.them}` });
        return;
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
      }
    }
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = file.name;
    link.click();
    URL.revokeObjectURL(url);
    setShared("Picture saved. Send it to them.");
  }

  const back = <button type="button" className="cr-back" onClick={onBack}><ArrowLeft aria-hidden="true" size={16} />Memories</button>;

  if (error && !read) {
    return <section className="screen cr-screen">{back}<div className="cr-state" role="alert"><h1>{error}</h1></div></section>;
  }
  if (!read || (making && read.state !== "ready")) {
    return (
      <section className="screen cr-screen" aria-busy="true">
        {back}
        <div className="cr-state">
          <span className="cr-pulse" aria-hidden="true" />
          <h1>{making ? "Reading your chat" : "Loading"}</h1>
          <p>{making ? "Counting who writes first, who laughs more, and what you two keep coming back to. About half a minute." : ""}</p>
        </div>
      </section>
    );
  }
  if (read.state !== "ready") {
    const why = WHY_NOT[read.state] ?? WHY_NOT.no_chat;
    return <section className="screen cr-screen">{back}<div className="cr-state"><h1>{why.title}</h1><p>{why.detail}</p></div></section>;
  }

  const { counts, written } = read;
  const rows = versus(counts);
  const first = counts.first_message;
  return (
    <section className="screen cr-screen">
      {back}
      <header className="cr-head">
        <span className="cr-eyebrow">The read</span>
        <h1>You &amp; {read.them}</h1>
        <p>{dateRange(counts.from, counts.to)} · {counts.messages.toLocaleString("en-IN")} messages</p>
        {written?.headline ? <p className="cr-headline">{written.headline}</p> : null}
      </header>

      <div className="cr-tiles">
        <div className="cr-tile"><strong>{counts.days_talked.toLocaleString("en-IN")}</strong><span>{counts.days_talked === 1 ? "day" : "days"} you talked, of {counts.span_days.toLocaleString("en-IN")}</span></div>
        <div className="cr-tile"><strong>{counts.longest_streak_days.toLocaleString("en-IN")}</strong><span>{counts.longest_streak_days === 1 ? "day" : "days"} in a row, your longest run</span></div>
        <div className="cr-tile"><strong>{counts.longest_silence_days.toLocaleString("en-IN")}</strong><span>{counts.longest_silence_days === 1 ? "day" : "days"}, your longest quiet</span></div>
      </div>

      {written?.roles.me || written?.roles.them ? (
        <div className="cr-roles">
          {written.roles.me ? <div><span>You</span><strong>{written.roles.me}</strong></div> : null}
          {written.roles.them ? <div><span>{read.them}</span><strong>{written.roles.them}</strong></div> : null}
        </div>
      ) : null}

      <article className="cr-card" aria-label="Side by side">
        <div className="cr-versus-head"><span>You</span><span>{read.them}</span></div>
        <ul className="cr-versus">
          {rows.map((row) => (
            <li key={row.id}>
              <div className="cr-versus-label">{row.label}</div>
              <div className="cr-versus-values">
                <span className={row.lead === "me" ? "is-lead" : ""}>{row.me}</span>
                <span className={row.lead === "them" ? "is-lead" : ""}>{row.them}</span>
              </div>
              <div className="cr-bar" aria-hidden="true"><span style={{ width: `${Math.min(96, Math.max(4, row.share))}%` }} /></div>
            </li>
          ))}
        </ul>
        <ul className="cr-facts">
          {sideFacts(counts).map((fact) => <li key={fact}>{fact}</li>)}
          {counts.me.top_emoji.length || counts.them.top_emoji.length ? (
            <li>Most used: you {counts.me.top_emoji.join(" ") || "none"}, {read.them} {counts.them.top_emoji.join(" ") || "none"}.</li>
          ) : null}
        </ul>
      </article>

      <article className="cr-card cr-first">
        <span className="cr-eyebrow">Where it started</span>
        <blockquote>{first.text}</blockquote>
        <p>{first.who === "me" ? "You" : read.them}, {dayText(first.date, true)}</p>
      </article>

      {written ? (
        <>
          {written.you_two ? <article className="cr-card"><h2>What this chat is like</h2><p>{written.you_two}</p></article> : null}
          {written.running_jokes.length ? (
            <article className="cr-card"><h2>Your running jokes</h2><ul className="cr-list">{written.running_jokes.map((item) => <li key={item.text}>{item.text}</li>)}</ul></article>
          ) : null}
          {written.keep_coming_back_to.length ? (
            <article className="cr-card"><h2>What you keep coming back to</h2><ul className="cr-list">{written.keep_coming_back_to.map((item) => <li key={item.text}>{item.text}</li>)}</ul></article>
          ) : null}
          {written.friction ? <article className="cr-card"><h2>Where you two bump</h2><p>{written.friction.text}</p></article> : null}
          {written.green_flag ? <article className="cr-card cr-green"><h2>The good thing</h2><p>{written.green_flag}</p></article> : null}
          {written.roast ? <article className="cr-card cr-roast"><span className="cr-eyebrow">The roast</span><p>{written.roast}</p></article> : null}
        </>
      ) : (
        <article className="cr-card"><h2>The words are missing</h2><p>Omi counted the chat but could not write about it this time. Try once more.</p></article>
      )}

      {error ? <p className="cr-error" role="alert">{error}</p> : null}
      <div className="cr-actions">
        <button type="button" className="cr-share" onClick={() => void share(read)}><Share2 aria-hidden="true" size={17} />Share as a picture</button>
        <button type="button" className="cr-again" disabled={making} onClick={() => void make(true)}><RefreshCw aria-hidden="true" size={15} className={making ? "is-spinning" : ""} />{making ? "Reading again" : "Read it again"}</button>
      </div>
      <p className="cr-note">The picture has your names, the headline, who does what, and the roast. No messages from the chat. Deleting the upload in Memories deletes this read too.</p>
      <canvas ref={canvasRef} className="cr-canvas" aria-hidden="true" />
      {shared ? <div className="mt-toast" role="status"><Check aria-hidden="true" /><span>{shared}</span></div> : null}
    </section>
  );
}
