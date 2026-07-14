import { AgentAvatar } from "./AgentAvatar";

type ChatBubbleProps = {
  role: "agent" | "user";
  children?: string;
  hint?: string;
  timestamp?: string;
  typing?: boolean;
};

export function ChatBubble({ role, children, hint, timestamp, typing = false }: ChatBubbleProps) {
  return (
    <div className={`chat-row ${role} ${typing ? "is-typing" : ""}`}>
      {role === "agent" ? <AgentAvatar /> : null}
      <div className="chat-bubble">
        {typing ? (
          <span className="typing-dots" aria-label="Omiryn is typing">
            <i />
            <i />
            <i />
          </span>
        ) : (
          <p>{children}</p>
        )}
        {hint ? <small>{hint}</small> : null}
      </div>
      {timestamp ? (
        <span className="message-meta" aria-hidden="true">
          {timestamp}
          {role === "user" ? " ✓✓" : ""}
        </span>
      ) : null}
    </div>
  );
}
