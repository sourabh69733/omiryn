// A ready read on the page: the numbers code counted for both people, what Omi wrote about the
// two of them, and the picture to share. Used by the read of a stored upload and by the read
// tried before sign-in. Its pieces sit straight in the page's column (.cr-screen).
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Check, Share2 } from "lucide-react";
import { type ChatRead, dateRange, dayText, drawReadCard, sideFacts, versus } from "./chatRead";

export type ReadyRead = Extract<ChatRead, { state: "ready" }>;

type Props = {
  read: ReadyRead;
  /** Something that went wrong outside the read itself (making it again), shown above the buttons. */
  error?: string;
  /** More buttons beside "Share as a picture". */
  children?: ReactNode;
  /** The small line under the buttons: what the picture holds and what happens to the read. */
  note: ReactNode;
};

export function ReadView({ read, error, children, note }: Props) {
  const [shared, setShared] = useState("");
  const [shareError, setShareError] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!shared) return;
    const timer = window.setTimeout(() => setShared(""), 5000);
    return () => window.clearTimeout(timer);
  }, [shared]);

  async function share() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setShareError("");
    // The picture uses the page's own fonts; wait for them or the first draw falls back.
    await document.fonts?.ready;
    drawReadCard(canvas, read);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) {
      setShareError("Could not make the picture.");
      return;
    }
    const file = new File([blob], `omiryn-read-${read.them.toLowerCase()}.png`, { type: "image/png" });
    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: `${read.me} & ${read.them}` });
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

  const { counts, written } = read;
  const rows = versus(counts);
  const first = counts.first_message;
  return (
    <>
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
            <article className="cr-card"><h2>Your running jokes</h2><ul className="cr-list">{written.running_jokes.map((item) => <li key={item.text}><strong>{item.text}</strong>{item.about ? <span>{item.about}</span> : null}</li>)}</ul></article>
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

      {error || shareError ? <p className="cr-error" role="alert">{error || shareError}</p> : null}
      <div className="cr-actions">
        <button type="button" className="cr-share" onClick={() => void share()}><Share2 aria-hidden="true" size={17} />Share as a picture</button>
        {children}
      </div>
      <p className="cr-note">{note}</p>
      <canvas ref={canvasRef} className="cr-canvas" aria-hidden="true" />
      {shared ? <div className="mt-toast" role="status"><Check aria-hidden="true" /><span>{shared}</span></div> : null}
    </>
  );
}
