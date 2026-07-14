type AgentAvatarProps = {
  mood?: "happy" | "thinking" | "wink";
};

export function AgentAvatar({ mood = "happy" }: AgentAvatarProps) {
  const wink = mood === "wink";
  return (
    <span className={`agent-avatar ${mood}`} aria-hidden="true">
      <svg viewBox="0 0 96 96" focusable="false">
        <circle className="agent-bg" cx="48" cy="48" r="44" />
        <path className="agent-body" d="M23 72c5-13 15-19 25-19s20 6 25 19" />
        <path
          className="agent-face"
          d="M29 43c0-14 9-24 21-24 11 0 19 9 19 22 0 16-10 28-22 28-10 0-18-11-18-26Z"
        />
        <path className="agent-line" d="M43 21c3-8 9-9 13-9-4 4-5 8-4 13" />
        <circle className="agent-eye" cx="40" cy="42" r="3.5" />
        {wink ? (
          <path className="agent-eye wink" d="M56 42h8" />
        ) : (
          <circle className="agent-eye" cx="60" cy="42" r="3.5" />
        )}
        <path className="agent-beak" d="M46 49h13l-6 7Z" />
        <circle className="agent-cheek" cx="35" cy="51" r="3" />
        <circle className="agent-cheek" cx="65" cy="51" r="3" />
        <circle className="agent-line" cx="62" cy="38" r="12" />
        <path className="agent-line" d="M70 47l12 12" />
        <path className="agent-bow" d="M34 73l13-8v16Zm28 0-13-8v16Z" />
      </svg>
    </span>
  );
}
