// The read before sign-in (/try): pick a WhatsApp chat with one person, say which name is you,
// and see what the chat says about the two of you. The chat is read once on the server and not
// saved. "Keep this read" holds the chat in this tab, signs the person in, and the app then
// shares it the usual way with the read they already saw (keepTry.ts).
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, FileText, Flame, Laugh, MessagesSquare, Upload } from "lucide-react";
import { apiErrorDetail, apiFetch } from "../../../lib/api";
import { trackTry } from "../../../lib/signInTracking";
import { OmirynLogo } from "../../brand/OmirynLogo";
import { CHAT_FILE_ACCEPT, chatFileText } from "../chatFile";
import { ReadView } from "../ReadView";
import { holdTry, type TriedRead } from "../tryRead";
import { type ChatSender, chatSenders, chatTitle } from "../whatsappSenders";

type Props = {
  onSignIn: () => Promise<void> | void;
  signingIn: boolean;
  authError: string | null;
  /** Back to the plain sign-in screen. */
  onClose: () => void;
};

type Picked = { fileName: string; text: string; senders: ChatSender[] };
type Answer =
  | { state: "ready"; read: TriedRead }
  | { state: "group_chat" | "too_short" }
  /** Today's free reads are used up: signing in still gets them the read. */
  | { state: "limit"; message: string };

const WHY_NOT: Record<string, { title: string; detail: string }> = {
  group_chat: { title: "This one is a group chat", detail: "The read works on a chat between two people. Pick a one-to-one chat." },
  too_short: { title: "Too little to read", detail: "Both of you need at least ten messages in the chat. Pick a longer one." },
};

export function TryReadPage({ onSignIn, signingIn, authError, onClose }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    trackTry("try_page_viewed");
  }, []);

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    setAnswer(null);
    setMe(null);
    try {
      const text = await chatFileText(file);
      const senders = chatSenders(text);
      if (!senders.length) {
        setPicked(null);
        setError("That doesn't look like a WhatsApp chat. Export a chat from WhatsApp and pick that file.");
        return;
      }
      trackTry("try_chat_picked", { people: Math.min(senders.length, 9) });
      if (senders.length > 2) {
        setPicked(null);
        setAnswer({ state: "group_chat" });
        return;
      }
      setPicked({ fileName: file.name, text, senders });
    } catch (caught) {
      setPicked(null);
      setError(caught instanceof Error ? caught.message : "Couldn't open that file.");
    }
  }

  async function read() {
    if (!picked || !me || reading) return;
    setReading(true);
    setError("");
    try {
      const response = await apiFetch("/api/public/chat-read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: picked.text, user_sender: me }),
      });
      if (response.status === 429 || response.status === 404) {
        const detail = await apiErrorDetail(response, "Sign in to get your read.");
        trackTry("try_read_shown", { state: "limit" });
        setAnswer({ state: "limit", message: detail.message });
        return;
      }
      if (!response.ok) throw new Error((await apiErrorDetail(response, "Couldn't read that chat. Try again.")).message);
      const body = (await response.json()) as TriedRead | { state: "group_chat" | "too_short" };
      trackTry("try_read_shown", { state: body.state });
      setAnswer(body.state === "ready" ? { state: "ready", read: body } : { state: body.state });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't read that chat. Try again.");
    } finally {
      setReading(false);
    }
  }

  function keep() {
    if (picked && me) {
      // Held in this tab only, for the trip to Google and back.
      holdTry({ text: picked.text, me, title: chatTitle(picked.fileName, picked.senders, me), kept: answer?.state === "ready" ? answer.read.kept ?? null : null });
    }
    trackTry("try_keep_started", { state: answer?.state ?? "none" });
    void onSignIn();
  }

  function startOver() {
    setPicked(null);
    setMe(null);
    setAnswer(null);
    setError("");
  }

  const signIn = (
    <>
      <button className="google-signin-button" type="button" onClick={keep} disabled={signingIn}>
        <span className="google-mark" aria-hidden="true">G</span>
        {signingIn ? "Opening Google..." : "Continue with Google"}
      </button>
      {authError ? <p className="auth-error" role="alert">{authError}</p> : null}
      <small>By continuing, you agree to Omiryn's <a href="https://omiryn.com/terms">Terms</a> and <a href="https://omiryn.com/privacy">Privacy Policy</a>.</small>
    </>
  );

  let body;
  if (reading) {
    body = (
      <div className="cr-state" role="status" aria-busy="true">
        <span className="cr-pulse" aria-hidden="true" />
        <h1>Reading your chat</h1>
        <p>Counting who writes first, finding your running jokes, writing the roast. About twenty seconds.</p>
      </div>
    );
  } else if (answer?.state === "ready") {
    body = (
      <>
        <button type="button" className="cr-back" onClick={startOver}><ArrowLeft aria-hidden="true" size={16} />Another chat</button>
        <ReadView read={answer.read} note="The picture has your names, the headline, who does what, and the roast. No messages from the chat.">{null}</ReadView>
        <section className="try-keep" aria-labelledby="try-keep-title">
          <h2 id="try-keep-title">Keep this read</h2>
          <p>Sign in and Omi keeps it, gets to know you from your side of this chat, and is there whenever you want to talk.</p>
          {signIn}
          <p className="try-quiet">Until you sign in, nothing from your chat is saved.</p>
        </section>
      </>
    );
  } else if (answer?.state === "limit") {
    body = (
      <>
        <div className="cr-state"><h1>Sign in for this one</h1><p>{answer.message}</p></div>
        <section className="try-keep" aria-label="Sign in">
          {signIn}
          <p className="try-quiet">{picked ? "Your chat waits in this tab and is read right after you sign in." : "After you sign in, share the chat from 📎 in chat."}</p>
        </section>
        <button type="button" className="try-link" onClick={startOver}>Pick another chat</button>
      </>
    );
  } else if (answer) {
    const why = WHY_NOT[answer.state];
    body = (
      <>
        <div className="cr-state"><h1>{why.title}</h1><p>{why.detail}</p></div>
        <button type="button" className="try-pick" onClick={() => { startOver(); inputRef.current?.click(); }}><Upload aria-hidden="true" size={18} />Choose another chat</button>
      </>
    );
  } else if (picked) {
    body = (
      <>
        <header className="cr-head">
          <span className="cr-eyebrow">The read</span>
          <h1>Which one is you?</h1>
          <p className="try-file"><FileText aria-hidden="true" size={14} /><span>{picked.fileName}</span></p>
        </header>
        <div className="try-names" role="radiogroup" aria-label="Your name in this chat">
          {picked.senders.map((sender) => (
            <button type="button" role="radio" aria-checked={me === sender.name} className={me === sender.name ? "is-active" : ""} key={sender.name} onClick={() => setMe(sender.name)}>
              <strong>{sender.name}</strong>
              <span>{sender.count.toLocaleString("en-IN")} {sender.count === 1 ? "message" : "messages"}</span>
            </button>
          ))}
        </div>
        {error ? <p className="cr-error" role="alert">{error}</p> : null}
        <button type="button" className="try-pick" disabled={!me} onClick={() => void read()}>Read this chat</button>
        <p className="cr-note">Your chat is read once to make this and is not saved. Phone numbers, emails and links are hidden first, then some of its lines go to the AI model that writes the words.</p>
        <button type="button" className="try-link" onClick={startOver}>Pick another file</button>
      </>
    );
  } else {
    body = (
      <>
        <header className="cr-head try-hero">
          <span className="cr-eyebrow">The read</span>
          <h1>What does your chat say about <em>you two?</em></h1>
          <p>Pick a WhatsApp chat with one person. Omi reads it and tells you what it is really like.</p>
        </header>
        <ul className="try-gets">
          <li><MessagesSquare aria-hidden="true" />Who writes first, who replies faster</li>
          <li><Laugh aria-hidden="true" />Your running jokes</li>
          <li><Flame aria-hidden="true" />A small roast for both of you</li>
        </ul>
        {error ? <p className="cr-error" role="alert">{error}</p> : null}
        <button type="button" className="try-pick" onClick={() => inputRef.current?.click()}><Upload aria-hidden="true" size={18} />Choose the chat file</button>
        <p className="try-quiet">No sign in. Nothing is saved.</p>
        <details className="try-how">
          <summary>How to get the file from WhatsApp</summary>
          <ol>
            <li>Open the chat with that person.</li>
            <li>iPhone: tap their name at the top. Android: tap ⋮, then More.</li>
            <li>Tap Export chat, then Without media.</li>
            <li>Save the file, come back here and pick it.</li>
          </ol>
        </details>
      </>
    );
  }

  return (
    <main className="try-page">
      <header className="try-top">
        <OmirynLogo />
        <a href="/" onClick={(event) => { event.preventDefault(); onClose(); }}>Sign in</a>
      </header>
      <section className="cr-screen try-screen">
        {body}
        <input ref={inputRef} type="file" accept={CHAT_FILE_ACCEPT} hidden onChange={(event) => void choose(event)} />
      </section>
    </main>
  );
}
