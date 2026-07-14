import { AgentAvatar } from "./AgentAvatar";

type ChatBubbleProps = {
  role: "agent" | "user";
  children: string;
  hint?: string;
};

export function ChatBubble({ role, children, hint }: ChatBubbleProps) {
  return (
    <div className={`chat-row ${role}`}>
      {role === "agent" ? <AgentAvatar /> : null}
      <div className="chat-bubble">
        <p>{children}</p>
        {hint ? <small>{hint}</small> : null}
      </div>
    </div>
  );
}
