// Memories page: give Omi a head start with a WhatsApp chat export or a few notes about yourself.
// Omi learns from the user's own lines only; deleting an upload removes what it taught.
import { type ChangeEvent, type FormEvent, useState } from "react";
import { FileText, MessageCircle, Upload } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { trackAppEvent } from "../../lib/appLogger";
import { Notice } from "./StateView";
import type { ContextSource } from "./types";

// Matches the API limits; a longer export keeps its most recent part.
const WHATSAPP_MAX_CHARS = 200000;
const NOTES_MAX_CHARS = 50000;

export function MemoryUploads({ sources, onChanged }: { sources: ContextSource[]; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"whatsapp" | "notes">("whatsapp");
  const [title, setTitle] = useState("");
  const [sender, setSender] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const content = await file.text();
    setText(content.slice(-WHATSAPP_MAX_CHARS));
    setFileName(file.name);
    if (!title) setTitle(file.name.replace(/^WhatsApp Chat (with )?/i, "").replace(/\.txt$/i, ""));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim().length < (mode === "whatsapp" ? 50 : 20)) {
      setError(mode === "whatsapp" ? "Choose a WhatsApp export (.txt) first." : "Write a little more first.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      // Uploads belong to the account; the route needs a chat, so use Omi's.
      const list = await (await apiFetch("/api/agent/conversations")).json();
      let conversationId = list.conversations?.[0]?.id as string | undefined;
      if (!conversationId) {
        const created = await apiFetch("/api/agent/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ agent_mode: "know_me" }) });
        conversationId = (await created.json()).id;
      }
      const name = title.trim() || (mode === "whatsapp" ? "WhatsApp chat" : "About me");
      const response = await apiFetch(
        mode === "whatsapp" ? `/api/agent/conversations/${conversationId}/whatsapp-import` : `/api/agent/conversations/${conversationId}/context-sources`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(mode === "whatsapp"
            ? { title: name, content: text, user_sender: sender.trim() || null, style_kind: "user_style", style_name: name }
            : { source_type: "manual_notes", title: name, content: text.trim().slice(0, NOTES_MAX_CHARS) }),
        },
      );
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't upload that."));
      trackAppEvent("memory_import_completed", { source_type: mode === "whatsapp" ? "whatsapp_chat" : "manual_notes" }, { page: "memories" });
      setOpen(false);
      setText(""); setTitle(""); setSender(""); setFileName("");
      setDone(true);
      await onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't upload that.");
    } finally {
      setSaving(false);
    }
  }

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
      <h2>Uploads {sources.length ? <span>{sources.length}</span> : null}</h2>
      <p className="mem-group-note">Give Omi a head start: a WhatsApp chat you're in, or a few lines about yourself. Omi learns only from your own messages. Deleting an upload also removes what Omi learned only from it.</p>
      {sources.length ? (
        <div className="mem-list">
          {sources.map((source) => (
            <article className="mem-row" key={source.id}>
              <div className="mem-row-copy"><small>{uploadKind(source.source_type)}</small><p>{source.title || "Upload"}</p></div>
              <div className="mem-row-actions">
                <button className="mem-link is-muted" type="button" onClick={() => void remove(source.id)} disabled={deletingId === source.id}>{deletingId === source.id ? "Deleting…" : "Delete"}</button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {done ? <Notice tone="success">Omi is reading it. New memories show up here in a few minutes.</Notice> : null}
      {open ? (
        <form className="mem-upload-form" onSubmit={submit}>
          <div className="mem-upload-modes" role="radiogroup" aria-label="What to upload">
            <button type="button" role="radio" aria-checked={mode === "whatsapp"} className={mode === "whatsapp" ? "is-active" : ""} onClick={() => setMode("whatsapp")}><MessageCircle aria-hidden="true" />WhatsApp chat</button>
            <button type="button" role="radio" aria-checked={mode === "notes"} className={mode === "notes" ? "is-active" : ""} onClick={() => setMode("notes")}><FileText aria-hidden="true" />Notes about me</button>
          </div>
          {mode === "whatsapp" ? (
            <>
              <p className="mem-upload-help">In WhatsApp, open a chat, then More → Export chat → Without media. Unzip it if needed and choose the .txt file.</p>
              <label className="mem-upload-file"><Upload aria-hidden="true" /><span>{fileName || "Choose the .txt file"}</span><input type="file" accept=".txt,text/plain" onChange={(event) => void readFile(event)} /></label>
              <label>Your name in that chat<input value={sender} maxLength={120} placeholder="As it appears in the export" onChange={(event) => setSender(event.target.value)} /></label>
              <label>Who is the chat with?<input value={title} maxLength={120} placeholder="A friend, a group…" onChange={(event) => setTitle(event.target.value)} /></label>
            </>
          ) : (
            <>
              <label>Title<input value={title} maxLength={120} placeholder="About me" onChange={(event) => setTitle(event.target.value)} /></label>
              <label>What should Omi know about you?<textarea value={text} rows={6} maxLength={NOTES_MAX_CHARS} placeholder="Where you live, what you do, what you're into, the kind of friends you get along with…" onChange={(event) => setText(event.target.value)} /></label>
            </>
          )}
          {error ? <Notice tone="error">{error}</Notice> : null}
          <div className="mem-upload-actions">
            <button type="button" className="secondary-button" onClick={() => { setOpen(false); setError(""); }} disabled={saving}>Cancel</button>
            <button type="submit" disabled={saving}>{saving ? "Uploading…" : "Upload"}</button>
          </div>
        </form>
      ) : (
        <button className="secondary-button mem-upload-open" type="button" onClick={() => { setOpen(true); setDone(false); }}><Upload aria-hidden="true" />Add an upload</button>
      )}
    </section>
  );
}

function uploadKind(sourceType?: string) {
  if (sourceType === "whatsapp_chat" || sourceType === "friend_style" || sourceType === "chat_export") return "WhatsApp chat";
  return "Notes";
}
