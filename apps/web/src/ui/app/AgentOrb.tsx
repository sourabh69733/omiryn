// The agent's face: a glossy "vibe" blob, not a photo of a person, since
// Omiryn is not a person. It breathes when idle; `active` marks the typing
// state (faster wobble plus a glow).
type AgentOrbProps = { active?: boolean };

export function AgentOrb({ active = false }: AgentOrbProps) {
  return (
    <span className={`agent-orb${active ? " is-active" : ""}`} aria-hidden="true">
      <span className="agent-orb-glow" />
      <img
        className="agent-orb-blob"
        src="/assets/agent/agent-idle-128.webp"
        srcSet="/assets/agent/agent-idle-128.webp 1x, /assets/agent/agent-idle-256.webp 2x"
        alt=""
        draggable={false}
        decoding="async"
      />
    </span>
  );
}
