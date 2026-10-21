// Memories page: what the user shared with Omi (from 📎 in chat), with Delete.
// Deleting an upload removes what Omi learned only from it.
import { useState } from "react";
import { apiFetch } from "../../lib/api";
import type { ContextSource } from "./types";

export function MemoryUploads({ sources, onChanged }: { sources: ContextSource[]; onChanged: () => Promise<void> }) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function remove(id: string) {
    setDeletingId(id);
    try {
      const response = await apiFetch(`/api/me/context-sources/${id}`, { method: "DELETE" });
      if (response.ok) await onChanged();
    } finally {
      setDeletingId(null);
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
              <div className="mem-row-copy"><small>{uploadKind(source.source_type)}{readingStatus(source) ? ` · ${readingStatus(source)}` : ""}</small><p>{source.title || "Upload"}</p></div>
              <div className="mem-row-actions">
                <button className="mem-link is-muted" type="button" onClick={() => void remove(source.id)} disabled={deletingId === source.id}>{deletingId === source.id ? "Deleting…" : "Delete"}</button>
              </div>
            </article>
          ))}
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
  if (reading.state === "done") return reading.learned ? `Learned ${reading.learned} ${reading.learned === 1 ? "thing" : "things"}` : "Read";
  if (reading.state === "failed") return "Couldn't finish, retrying";
  if (reading.state === "reading" && reading.parts) return `Reading ${reading.parts_done ?? 0} of ${reading.parts}`;
  return reading.state === "merging" ? "Almost done" : "Reading…";
}
