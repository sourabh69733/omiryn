// Profile > Account: chat with Omi on Telegram. Connecting opens the bot with a one-time code;
// tapping Start there finishes it. Hidden when Telegram isn't switched on for this account.
import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { Notice } from "./StateView";

type TelegramStatus = { available: boolean; connected: boolean; bot_username: string | null };

export function TelegramSetting() {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [busy, setBusy] = useState(false);
  // Set while waiting for the user to tap Start in Telegram.
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      const response = await apiFetch("/api/channels/telegram");
      if (!response.ok) return;
      const next = (await response.json()) as TelegramStatus;
      setStatus(next);
      if (next.connected) setPendingUrl(null);
    } catch {
      // Optional row; Profile works without it.
    }
  }

  useEffect(() => { void refresh(); }, []);

  // Coming back from Telegram after tapping Start shows "Connected" without a reload.
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
      const response = await apiFetch("/api/channels/telegram/link", { method: "POST" });
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
      const response = await apiFetch("/api/channels/telegram", { method: "DELETE" });
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
          <span>Telegram</span>
          <span className="pf-telegram-state">
            <span className="pf-muted">Connected</span>
            <button type="button" className="pf-telegram-action" onClick={() => void disconnect()} disabled={busy}>Disconnect</button>
          </span>
        </div>
      ) : (
        <button type="button" className="pf-row is-action" onClick={() => void connect()} disabled={busy}>
          <span>Chat with Omi on Telegram</span>
          <span className="pf-muted pf-model-current">{busy ? "Opening…" : "Connect"}<ChevronRight aria-hidden="true" /></span>
        </button>
      )}
      {pendingUrl && !status.connected ? (
        <p className="pf-model-note pf-telegram-note">
          Tap Start in Telegram to finish. The link works for 15 minutes. <a href={pendingUrl} target="_blank" rel="noreferrer">Open Telegram</a>
        </p>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}
    </>
  );
}
