// Profile > Account: chat with Omi on a messaging app (Telegram, WhatsApp). Connecting opens the
// app with a one-time code; Start (Telegram) or send (WhatsApp) there finishes it. Hidden when
// that app isn't switched on for this account.
import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { Notice } from "./StateView";

type ChannelStatus = { available: boolean; connected: boolean };
type Channel = "telegram" | "whatsapp";

const CHANNEL_COPY: Record<Channel, { name: string; finish: string }> = {
  telegram: { name: "Telegram", finish: "Tap Start in Telegram to finish." },
  whatsapp: { name: "WhatsApp", finish: "Send the message that opens in WhatsApp to finish." },
};

// Omi as a chat bubble: Omi's own chat in that app.
function ChannelIcon() {
  return <img className="pf-channel-icon" src="/assets/agent/omi-chat-bubble-48.webp" srcSet="/assets/agent/omi-chat-bubble-48.webp 1x, /assets/agent/omi-chat-bubble-96.webp 2x" width={24} height={24} alt="" />;
}

export function ChannelSetting({ channel }: { channel: Channel }) {
  const copy = CHANNEL_COPY[channel];
  const [status, setStatus] = useState<ChannelStatus | null>(null);
  const [busy, setBusy] = useState(false);
  // Set while waiting for the user to finish in the app.
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      const response = await apiFetch(`/api/channels/${channel}`);
      if (!response.ok) return;
      const next = (await response.json()) as ChannelStatus;
      setStatus(next);
      if (next.connected) setPendingUrl(null);
    } catch {
      // Optional row; Profile works without it.
    }
  }

  useEffect(() => { void refresh(); }, []);

  // Coming back from the app after finishing shows "Connected" without a reload.
  useEffect(() => {
    if (!pendingUrl) return;
    const onReturn = () => { if (document.visibilityState === "visible") void refresh(); };
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [pendingUrl]);

  if (!status?.available) return null;

  async function connect() {
    // Opened before the request so the browser treats it as the user's tap, not a popup.
    const tab = window.open("", "_blank");
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`/api/channels/${channel}/link`, { method: "POST" });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't start connecting."));
      const { url } = (await response.json()) as { url: string };
      setPendingUrl(url);
      if (tab) tab.location.href = url;
    } catch (caught) {
      tab?.close();
      setError(caught instanceof Error ? caught.message : "Couldn't start connecting.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`/api/channels/${channel}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't disconnect."));
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't disconnect.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {status.connected ? (
        <div className="pf-row">
          <span className="pf-channel-label"><ChannelIcon />{copy.name}</span>
          <span className="pf-channel-state">
            <span className="pf-muted">Connected</span>
            <button type="button" className="pf-channel-action" onClick={() => void disconnect()} disabled={busy}>Disconnect</button>
          </span>
        </div>
      ) : (
        <button type="button" className="pf-row is-action" onClick={() => void connect()} disabled={busy}>
          <span className="pf-channel-label"><ChannelIcon />Chat with Omi on {copy.name}</span>
          <span className="pf-muted pf-model-current">{busy ? "Opening…" : "Connect"}<ChevronRight aria-hidden="true" /></span>
        </button>
      )}
      {pendingUrl && !status.connected ? (
        <p className="pf-model-note pf-channel-note">
          {copy.finish} The link works for 15 minutes. <a href={pendingUrl} target="_blank" rel="noreferrer">Open {copy.name}</a>
        </p>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}
    </>
  );
}
