type AgentAvatarProps = {
  mood?: "happy" | "thinking" | "wink";
};

export function AgentAvatar({ mood = "happy" }: AgentAvatarProps) {
  return (
    <span className={`agent-avatar ${mood}`} aria-hidden="true">
      <span className="agent-sprout" />
      <span className="agent-face-mark">
        <i />
        <i />
        <b />
      </span>
    </span>
  );
}
