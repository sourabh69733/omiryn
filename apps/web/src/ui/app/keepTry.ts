// After sign-in: the chat the person tried on /try is shared the usual way, once, with the seal
// of the read they already saw, so that read is kept and Omi starts learning from their side.
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { trackAppEvent } from "../../lib/appLogger";
import type { HeldTry } from "./tryRead";
import type { SharedUpload } from "./UploadReading";

export async function shareHeldTry(conversationId: string, held: HeldTry): Promise<SharedUpload> {
  const response = await apiFetch(`/api/agent/conversations/${conversationId}/whatsapp-import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: held.title, content: held.text, user_sender: held.me, style_kind: "user_style", style_name: held.title, kept_read: held.kept }),
  });
  if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't keep your chat. Share it again from 📎."));
  trackAppEvent("memory_import_completed", { source_type: "whatsapp_chat", from: "try" }, { page: "chat" });
  const source = (await response.json()) as { id: string };
  return { sourceId: source.id, label: `your chat with ${held.title}` };
}
