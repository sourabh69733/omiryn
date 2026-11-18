// The read of one uploaded chat (/read/<upload id>): the numbers code counted for both people,
// what Omi wrote about the two of them, and a picture to share. Made on the first visit.
import { useEffect, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import type { ChatRead } from "../chatRead";
import { ReadView } from "../ReadView";

type Props = {
  sourceId: string;
  onBack: () => void;
  /** Where back leads: "Memories", or "Omi" when the read was opened from the chat. */
  backLabel?: string;
};

// A read being made at upload is polled this often, this many times, before the page makes it itself.
const WAIT_MS = 2500;
const WAIT_TRIES = 36;

const WHY_NOT: Record<string, { title: string; detail: string }> = {
  group_chat: { title: "This one is a group chat", detail: "The read works on a chat between two people. Share a one-to-one chat from 📎 in chat." },
  too_short: { title: "Too little to read", detail: "Both of you need at least ten messages in the chat for a read." },
  no_chat: { title: "Nothing to read here", detail: "This upload is notes, not a chat between two people." },
};

export function ChatReadPage({ sourceId, onBack, backLabel = "Memories" }: Props) {
  const [read, setRead] = useState<ChatRead | null>(null);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState("");

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
      let stored: ChatRead = await response.json();
      // The read is made while the chat uploads. If that is still going, wait for it; never start a second one.
      for (let tries = 0; stored.state === "making" && tries < WAIT_TRIES && !cancelled; tries += 1) {
        setRead(stored);
        await new Promise((resolve) => window.setTimeout(resolve, WAIT_MS));
        if (cancelled) return;
        const again = await apiFetch(`/api/me/context-sources/${sourceId}/chat-read`);
        if (!again.ok) break;
        stored = await again.json();
      }
      if (cancelled) return;
      if (stored.state !== "none" && stored.state !== "making") {
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

  const back = <button type="button" className="cr-back" onClick={onBack}><ArrowLeft aria-hidden="true" size={16} />{backLabel}</button>;

  if (error && !read) {
    return <section className="screen cr-screen">{back}<div className="cr-state" role="alert"><h1>{error}</h1></div></section>;
  }
  if (!read || read.state === "making" || (making && read.state !== "ready")) {
    const waiting = read?.state === "making";
    return (
      <section className="screen cr-screen" aria-busy="true">
        {back}
        <div className="cr-state">
          <span className="cr-pulse" aria-hidden="true" />
          <h1>{waiting ? "Almost ready" : making ? "Putting it together" : "Loading"}</h1>
          <p>{waiting ? "Omi started on this when you shared the chat. A few more seconds." : making ? "Omi already has the chat. It is finding your running jokes and writing the roast. About fifteen seconds." : ""}</p>
        </div>
      </section>
    );
  }
  if (read.state !== "ready") {
    const why = WHY_NOT[read.state] ?? WHY_NOT.no_chat;
    return <section className="screen cr-screen">{back}<div className="cr-state"><h1>{why.title}</h1><p>{why.detail}</p></div></section>;
  }

  return (
    <section className="screen cr-screen">
      {back}
      <ReadView read={read} error={error} note="The picture has your names, the headline, who does what, and the roast. No messages from the chat. Deleting the upload in Memories deletes this read too.">
        <button type="button" className="cr-again" disabled={making} onClick={() => void make(true)}><RefreshCw aria-hidden="true" size={15} className={making ? "is-spinning" : ""} />{making ? "Reading again" : "Read it again"}</button>
      </ReadView>
    </section>
  );
}
