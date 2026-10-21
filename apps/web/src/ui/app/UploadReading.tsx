// The note above the composer while Omi reads a shared chat: real progress from the server, then
// how much it learned. The upload is remembered in this browser, so a reload shows it again.
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { apiFetch } from "../../lib/api";

export type SharedUpload = { sourceId: string; label: string };
type Reading = { state: string; parts?: number; parts_done?: number; learned?: number };

const STORAGE_KEY = "omiryn.upload_reading";
const POLL_MS = 3000;

export function rememberUpload(upload: SharedUpload | null) {
  try {
    if (upload) localStorage.setItem(STORAGE_KEY, JSON.stringify(upload));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Private mode or blocked storage: the note just won't survive a reload.
  }
}

export function rememberedUpload(): SharedUpload | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SharedUpload) : null;
  } catch {
    return null;
  }
}

export function UploadReading({ upload, onDismiss }: { upload: SharedUpload; onDismiss: () => void }) {
  const [reading, setReading] = useState<Reading>({ state: "queued" });

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    async function check() {
      try {
        const response = await apiFetch(`/api/me/context-sources/${upload.sourceId}/reading`);
        if (response.status === 404) return onDismiss();
        if (response.ok) {
          const next = (await response.json()) as Reading;
          if (stopped) return;
          setReading(next);
          // A failed read is retried by the server, so keep checking.
          if (next.state === "done" || next.state === "none") return;
        }
      } catch {
        // Offline for a moment: try again on the next tick.
      }
      if (!stopped) timer = window.setTimeout(() => void check(), POLL_MS);
    }
    void check();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [upload.sourceId, onDismiss]);

  return (
    <div className="omi-readonly-bar upload-note" role="status">
      <span>{readingText(reading, upload.label)}</span>
      <button type="button" className="upload-note-close" onClick={onDismiss} aria-label="Dismiss"><X aria-hidden="true" /></button>
    </div>
  );
}

export function readingText(reading: Reading, label: string) {
  const parts = reading.parts ?? 0;
  switch (reading.state) {
    case "reading":
      return parts ? `Omi is reading ${label}… ${reading.parts_done ?? 0} of ${parts} parts` : `Omi is reading ${label}…`;
    case "merging":
      return `Omi is putting together what it learned from ${label}…`;
    case "done":
      return reading.learned
        ? `Done. Omi learned ${reading.learned} ${reading.learned === 1 ? "thing" : "things"} from ${label}.`
        : `Done reading ${label}. Nothing new to remember.`;
    case "failed":
      return `Omi couldn't finish reading ${label}. It will try again in a minute.`;
    case "none":
      return `Omi has read ${label}.`;
    default:
      return `Omi will start reading ${label} in a moment…`;
  }
}
