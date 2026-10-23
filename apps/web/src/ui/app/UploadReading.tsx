// The note above the composer while Omi reads a shared chat: real progress from the server, then
// how much it learned. The upload is remembered in this browser, so a reload shows it again.
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { apiFetch } from "../../lib/api";

export type SharedUpload = { sourceId: string; label: string };
type Reading = {
  state: string;
  parts?: number;
  parts_done?: number;
  learned?: number;
  topics?: number;
  started_at?: string;
  finished_at?: string;
};

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
  const [now, setNow] = useState(() => Date.now());

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

  const finished = reading.state === "done" || reading.state === "none";
  useEffect(() => {
    if (finished) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [finished]);

  const step = STEPS.findIndex((item) => item.state === reading.state);
  const elapsed = elapsedText(reading, now);
  return (
    <div className={`omi-readonly-bar upload-note upload-progress${reading.state === "failed" ? " is-failed" : ""}${finished ? " is-done" : ""}`} role="status">
      <div className="upload-progress-copy">
        <div className="upload-progress-head">
          <strong>{readingText(reading, upload.label)}</strong>
          {elapsed ? <span className="upload-progress-time">{elapsed}</span> : null}
        </div>
        {reading.state !== "none" ? (
          <ol className="upload-steps" aria-label="Steps">
            {STEPS.map((item, index) => {
              const status = finished || index < step ? "is-done" : index === step ? "is-active" : "";
              return (
                <li key={item.state} className={status}>
                  <span aria-hidden="true">{finished || index < step ? "✓" : index + 1}</span>
                  {item.label}
                  {index === 0 && reading.state === "reading" && reading.parts ? ` ${reading.parts_done ?? 0}/${reading.parts}` : ""}
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
      <button type="button" className="upload-note-close" onClick={onDismiss} aria-label="Dismiss"><X aria-hidden="true" /></button>
    </div>
  );
}

const STEPS = [
  { state: "reading", label: "Reading" },
  { state: "merging", label: "Putting together" },
  { state: "indexing", label: "Making it searchable" },
];

export function readingText(reading: Reading, label: string) {
  switch (reading.state) {
    case "reading":
      return `Step 1 of 3 · Omi is reading ${label}`;
    case "merging":
      return `Step 2 of 3 · Putting together what Omi learned`;
    case "indexing":
      return `Step 3 of 3 · Making ${label} searchable`;
    case "done": {
      const learned = reading.learned ? `${reading.learned} ${reading.learned === 1 ? "thing" : "things"} about you` : "";
      const topics = reading.topics ? `${reading.topics} ${reading.topics === 1 ? "topic" : "topics"}` : "";
      const found = [learned, topics].filter(Boolean).join(", ");
      return found ? `✓ Done · learned ${found}. Ask Omi anything about ${label}.` : `✓ Done reading ${label}. Ask Omi anything about it.`;
    }
    case "failed":
      return `Couldn't finish reading ${label}. Trying again in a minute.`;
    case "none":
      return `Omi has read ${label}.`;
    default:
      return `Starting to read ${label}…`;
  }
}

function elapsedText(reading: Reading, now: number) {
  const started = reading.started_at ? Date.parse(reading.started_at) : NaN;
  if (Number.isNaN(started)) return "";
  const end = reading.state === "done" && reading.finished_at ? Date.parse(reading.finished_at) : now;
  const seconds = Math.max(0, Math.round((end - started) / 1000));
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return reading.state === "done" ? `took ${clock}` : clock;
}
