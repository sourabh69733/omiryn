import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, MessageCircle } from "lucide-react";

type StateViewProps = {
  kind: "loading" | "empty" | "error";
  title: string;
  detail?: string;
  /** "Try again" on errors; any buttons on empty states. */
  onRetry?: () => void;
  children?: ReactNode;
};

// One look for every screen's loading, empty and error state.
export function StateView({ kind, title, detail, onRetry, children }: StateViewProps) {
  return (
    <div className={`state-view is-${kind}`} role={kind === "error" ? "alert" : "status"} aria-live="polite">
      <span className="state-view-mark" aria-hidden="true">
        {kind === "loading" ? <span className="state-view-spinner" /> : kind === "error" ? <AlertCircle /> : <MessageCircle />}
      </span>
      <strong>{title}</strong>
      {detail ? <span className="state-view-detail">{detail}</span> : null}
      {onRetry || children ? (
        <div className="state-view-actions">
          {onRetry ? <button type="button" className="secondary-button" onClick={onRetry}>Try again</button> : null}
          {children}
        </div>
      ) : null}
    </div>
  );
}

type NoticeProps = { tone: "success" | "error" | "info"; children: ReactNode };

// A one-line message under an action: saved, removed, or what went wrong.
export function Notice({ tone, children }: NoticeProps) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "error" ? AlertCircle : Info;
  return (
    <p className={`notice is-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}
