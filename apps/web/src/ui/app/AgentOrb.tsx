// The agent's face: a glossy "vibe" blob, not a photo of a person, since
// Omiryn is not a person. Each state has its own image; CSS adds a faint
// breath and light sweep so it feels alive without bouncing around.
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
      <img
        key={current}
        className="agent-orb-blob"
        src={`/assets/agent/agent-${current}-128.webp`}
        srcSet={`/assets/agent/agent-${current}-128.webp 1x, /assets/agent/agent-${current}-256.webp 2x`}
        alt=""
        draggable={false}
        decoding="async"
      />
    </span>
  );
}
