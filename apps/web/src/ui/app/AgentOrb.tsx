// Replaces the illustrated agent avatar. A soft animated orb, not a photo of a
// person, since Omiryn is not a person. `active` marks the typing state.
type AgentOrbProps = { active?: boolean };

export function AgentOrb({ active = false }: AgentOrbProps) {
  return (
    <span className={`agent-orb${active ? " is-active" : ""}`} aria-hidden="true">
      <span className="agent-orb-core" />
      <span className="agent-orb-wave" />
    </span>
  );
}
