// The agent's face: an ember drop drawn in CSS (see .agent-orb in chat.css), not a photo of a
// person, since Omiryn is not a person. Only "thinking" (writing a reply) moves; every other
// state holds a slightly different shape and is still.
export type AgentOrbState = "idle" | "thinking" | "listening" | "happy";

type AgentOrbProps = {
  state?: AgentOrbState;
  /** Older callers: `active` means the agent is writing a reply. */
  active?: boolean;
};

export function AgentOrb({ state, active = false }: AgentOrbProps) {
  const current: AgentOrbState = state ?? (active ? "thinking" : "idle");
  return (
    <span className={`agent-orb is-${current}`} aria-hidden="true">
      <span className="agent-orb-glow" />
      <span className="agent-orb-blob" />
    </span>
  );
}
