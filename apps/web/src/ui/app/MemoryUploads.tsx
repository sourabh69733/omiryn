// Memories page: what the user shared with Omi (from 📎 in chat), with Delete.
// Deleting an upload removes what Omi learned only from it; a prompt says exactly what goes first.
import { useState } from "react";
import { ArrowRight, Sparkles, Trash2 } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { readButton, readLabel } from "./chatRead";
import { Notice } from "./StateView";
import { uploadDeleteLines } from "./uploadDelete";
import type { ContextSource } from "./types";

export function MemoryUploads({ sources, onChanged, onOpenRead }: { sources: ContextSource[]; onChanged: () => Promise<void>; onOpenRead?: (sourceId: string) => void }) {
  const [pending, setPending] = useState<ContextSource | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  function ask(source: ContextSource) {
    setError("");
    setPending(source);
  }

  function close() {
    if (!deleting) setPending(null);
  }

  async function remove(id: string) {
    setDeleting(true);
    setError("");
    try {
      const response = await apiFetch(`/api/me/context-sources/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not delete it. Try again."));
      setPending(null);
      await onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete it. Try again.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="mem-group mem-uploads">
      <h2>Shared with Omi {sources.length ? <span>{sources.length}</span> : null}</h2>
      <p className="mem-group-note">
        {sources.length
          ? "Chats you shared from 📎 in chat. Deleting one also removes what Omi learned only from it."
          : "Share a WhatsApp chat from 📎 in chat and Omi gets to know you faster. Only your own messages teach it."}
      </p>
      {sources.length ? (
        <div className="mem-list">
          {sources.map((source) => (
            <article className="mem-row" key={source.id}>
              <div className="mem-row-copy">
                <small>{uploadKind(source.source_type)}{readingStatus(source) ? ` · ${readingStatus(source)}` : ""}</small>
                <p>{source.title || "Upload"}</p>
                {source.digest?.summary || source.digest?.topics?.length ? (
                  <details className="mem-upload-digest">
                    <summary>What Omi took from it</summary>
                    {source.digest.summary ? <p>{source.digest.summary}</p> : null}
                    {source.digest.topics?.length ? (
                      <ul>{source.digest.topics.map((topic) => <li key={topic.title}>{topic.title}{topic.started ? <span> · {shortDate(topic.started)}</span> : null}</li>)}</ul>
                    ) : null}
                  </details>
                ) : null}
              </div>
              <div className="mem-row-actions">
                {onOpenRead && readButton(source.source_type, source.digest?.read) === "open" ? (
                  <button className="mem-read" type="button" onClick={() => onOpenRead(source.id)} aria-label={`What this chat says about you two: ${source.title || "this chat"}`}>
                    <Sparkles aria-hidden="true" size={15} /><span>{readLabel(source.title)}</span><ArrowRight aria-hidden="true" size={15} />
                  </button>
                ) : null}
                {onOpenRead && readButton(source.source_type, source.digest?.read) === "making" ? <span className="mem-read is-making" role="status"><span className="mem-read-dot" aria-hidden="true" />Getting your read ready</span> : null}
                <button className="mem-link is-muted" type="button" onClick={() => ask(source)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {pending ? (
        <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-upload-title" aria-describedby="delete-upload-copy" onKeyDown={(event) => { if (event.key === "Escape") close(); }}>
            <div className="confirm-icon" aria-hidden="true"><Trash2 /></div>
            <div className="confirm-copy">
              <h2 id="delete-upload-title">Delete this shared chat?</h2>
              <p id="delete-upload-copy">This deletes:</p>
              <ul className="delete-impact">
                {uploadDeleteLines(pending).map((line) => <li key={line}>{line}</li>)}
              </ul>
              <p>What you also told Omi in your chats stays. This can't be undone.</p>
              <p className="confirm-session">{pending.title || "Upload"}</p>
              {error ? <Notice tone="error">{error}</Notice> : null}
            </div>
            <div className="confirm-actions">
              <button className="secondary-button" type="button" autoFocus onClick={close} disabled={deleting}>Cancel</button>
              <button className="danger-button" type="button" onClick={() => void remove(pending.id)} disabled={deleting}>{deleting ? "Deleting…" : "Delete"}</button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function uploadKind(sourceType?: string) {
  if (sourceType === "whatsapp_chat" || sourceType === "friend_style" || sourceType === "chat_export") return "WhatsApp chat";
  return "Notes";
}

function readingStatus(source: ContextSource) {
  const reading = source.metadata?.reading;
  if (!reading) return "";
  if (reading.state === "done") {
    const parts = [
      reading.learned ? `${reading.learned} ${reading.learned === 1 ? "thing" : "things"} about you` : "",
      reading.topics ? `${reading.topics} ${reading.topics === 1 ? "topic" : "topics"}` : "",
    ].filter(Boolean);
    return parts.length ? `Learned ${parts.join(", ")}` : "Read";
  }
  if (reading.state === "failed") return "Couldn't finish, retrying";
  if (reading.state === "reading" && reading.parts) return `Reading ${reading.parts_done ?? 0} of ${reading.parts}`;
  if (reading.state === "merging") return "Understanding";
  if (reading.state === "indexing") return "Saving";
  return "Reading…";
}

function shortDate(day: string) {
  const date = new Date(`${day}T12:00:00`);
  return Number.isNaN(date.getTime()) ? day : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
