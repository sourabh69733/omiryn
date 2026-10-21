// 📎 in the composer: share a WhatsApp chat so Omi gets to know you faster.
// Pick the exported .txt, tap which name is you, share. Omi learns from your lines only.
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { Paperclip, X } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { trackAppEvent } from "../../lib/appLogger";
import type { SharedUpload } from "./UploadReading";
import { type ChatSender, chatSenders, chatTitle } from "./whatsappSenders";

// The API's limit; a longer export keeps its most recent part.
const MAX_CHARS = 200000;
const MAX_NAMES = 6;

type Picked = { fileName: string; text: string; senders: ChatSender[] };

export function ChatUpload({ conversationId, disabled, onShared }: { conversationId: string | null; disabled?: boolean; onShared: (upload: SharedUpload) => void }) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!picked) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (sharing) return;
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !panelRef.current?.contains(event.target as Node)) setPicked(null);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [picked, sharing]);

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const text = (await file.text()).slice(-MAX_CHARS);
    setError("");
    setMe(null);
    setPicked({ fileName: file.name, text, senders: chatSenders(text) });
  }

  async function share() {
    if (!picked || !conversationId) return;
    const isChat = picked.senders.length > 0;
    if (isChat && !me) return;
    setSharing(true);
    setError("");
    try {
      const title = isChat ? chatTitle(picked.fileName, picked.senders, me) : picked.fileName.replace(/\.txt$/i, "") || "Notes";
      const response = await apiFetch(
        isChat ? `/api/agent/conversations/${conversationId}/whatsapp-import` : `/api/agent/conversations/${conversationId}/context-sources`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(isChat
            ? { title, content: picked.text, user_sender: me, style_kind: "user_style", style_name: title }
            : { source_type: "manual_notes", title, content: picked.text.slice(0, 50000) }),
        },
      );
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't share that file."));
      trackAppEvent("memory_import_completed", { source_type: isChat ? "whatsapp_chat" : "manual_notes" }, { page: "chat" });
      setPicked(null);
      const source = (await response.json()) as { id: string };
      onShared({ sourceId: source.id, label: isChat ? `your chat with ${title}` : "your notes" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't share that file.");
    } finally {
      setSharing(false);
    }
  }

  const isChat = Boolean(picked?.senders.length);
  return (
    <div className="chat-upload" ref={panelRef}>
      <button type="button" className="chat-upload-button" disabled={disabled || !conversationId} aria-label="Share a WhatsApp chat" title="Share a WhatsApp chat" onClick={() => inputRef.current?.click()}><Paperclip aria-hidden="true" /></button>
      <input ref={inputRef} type="file" accept=".txt,text/plain" hidden onChange={(event) => void choose(event)} />
      {picked ? (
        <div className="chat-upload-panel" role="dialog" aria-label="Share with Omi">
          <div className="chat-upload-head">
            <strong>{isChat ? "Which one is you?" : "Share these notes?"}</strong>
            <button type="button" aria-label="Cancel" onClick={() => setPicked(null)} disabled={sharing}><X aria-hidden="true" /></button>
          </div>
          {isChat ? (
            <div className="chat-upload-names" role="radiogroup" aria-label="Your name in this chat">
              {picked!.senders.slice(0, MAX_NAMES).map((sender) => (
                <button type="button" role="radio" aria-checked={me === sender.name} className={me === sender.name ? "is-active" : ""} key={sender.name} onClick={() => setMe(sender.name)}>{sender.name}</button>
              ))}
            </div>
          ) : (
            <p className="chat-upload-note">This isn't a WhatsApp chat, so Omi will read it as notes about you.</p>
          )}
          <p className="chat-upload-note">Only your messages teach Omi. Numbers, emails and links are hidden. Delete it any time in Memories.</p>
          {error ? <p className="chat-upload-error" role="alert">{error}</p> : null}
          <button type="button" className="chat-upload-share" disabled={sharing || (isChat && !me)} onClick={() => void share()}>{sharing ? "Sharing…" : "Share with Omi"}</button>
        </div>
      ) : null}
    </div>
  );
}
