import { AgentOrb } from "../app/AgentOrb";

type AgentAvatarProps = {
  mood?: "happy" | "thinking" | "wink";
};

// Onboarding uses the same vibe blob as the main chat; "thinking" wobbles.
export function AgentAvatar({ mood = "happy" }: AgentAvatarProps) {
  return (
    <span className="agent-avatar" aria-hidden="true">
      <AgentOrb active={mood === "thinking"} />
    </span>
  );
}
