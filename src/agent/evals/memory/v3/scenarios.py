"""Scenario catalogue for semantic quality and lifecycle behavior of v3 memories."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.processing import MemoryHandoff


@dataclass(frozen=True)
class ExistingMemoryV3Fixture:
    """One memory supplied as active state or inactive lifecycle history."""

    id: str
    memory_kind: str
    purposes: tuple[str, ...]
    key: str
    value: Any
    sensitivity: str = "standard"
    confidence: float = 0.9
    importance: float = 0.7
    status: str = "active"

    def as_context(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_kind": self.memory_kind,
            "purposes": list(self.purposes),
            "key": self.key,
            "value": self.value,
            "sensitivity": self.sensitivity,
            "confidence": self.confidence,
            "importance": self.importance,
            "status": self.status,
            "targetable": self.status == "active",
        }


@dataclass(frozen=True)
class ExpectedMemoryV3Operation:
    """Core semantic expectation that permits harmless wording differences."""

    operation: str
    memory_kind: str | None = None
    required_purposes: tuple[str, ...] = ()
    forbidden_purposes: tuple[str, ...] = ()
    target_memory_id: str | None = None
    value_concepts: tuple[str, ...] = ()
    evidence_message_indexes: tuple[int, ...] = ()
    sensitivity: str | None = None


@dataclass(frozen=True)
class MemoryV3Scenario:
    """One bounded conversation and its expected canonical-memory behavior."""

    id: str
    description: str
    messages: tuple[dict[str, Any], ...]
    expected_operations: tuple[ExpectedMemoryV3Operation, ...] = ()
    optional_operations: tuple[ExpectedMemoryV3Operation, ...] = ()
    expected_decision: str = "propose"
    existing_memories: tuple[ExistingMemoryV3Fixture, ...] = ()
    processed_through_message_index: int = -1
    previous_handoff: MemoryHandoff = field(default_factory=MemoryHandoff)
    forbidden_concepts: tuple[str, ...] = ()
    allow_additional_operations: bool = False
    tags: tuple[str, ...] = ("memory_v3",)
    # Vibe card: None skips the check; otherwise only these areas may get a line.
    allowed_vibe_areas: tuple[str, ...] | None = None
    required_vibe_areas: tuple[str, ...] = ()
    # Vibe-only scenarios do not grade the memory decision or operations.
    grade_memory_operations: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.description.strip() or not self.messages:
            raise ValueError("V3 memory scenarios require an id, description, and messages.")
        if self.expected_decision not in {"propose", "no_change"}:
            raise ValueError("Expected decision must be propose or no_change.")
        if self.expected_decision == "no_change" and self.expected_operations:
            raise ValueError("A no_change scenario cannot expect operations.")
        indexes = set(range(len(self.messages)))
        for expected in (*self.expected_operations, *self.optional_operations):
            if not set(expected.evidence_message_indexes).issubset(indexes):
                raise ValueError(f"Scenario '{self.id}' contains an unknown evidence index.")
        if self.allowed_vibe_areas is not None and not set(self.required_vibe_areas) <= set(
            self.allowed_vibe_areas
        ):
            raise ValueError(f"Scenario '{self.id}' requires a vibe area it does not allow.")
        memory_ids = {memory.id for memory in self.existing_memories}
        if len(memory_ids) != len(self.existing_memories):
            raise ValueError(f"Scenario '{self.id}' contains duplicate memory ids.")


MEMORY_V3_SCENARIOS = (
    MemoryV3Scenario(
        id="capture_current_location_as_semantic_profile",
        description="A stated current home is stable semantic profile knowledge.",
        messages=({"role": "user", "content": "I live in Pune now."},),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("profile",),
                value_concepts=("pune",),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "semantic", "profile", "add"),
    ),
    MemoryV3Scenario(
        id="capture_work_background_as_semantic_profile",
        description="Explicit work background describes the user, not partner compatibility.",
        messages=({"role": "user", "content": "I build a matchmaking product called Omiryn."},),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("profile",),
                forbidden_purposes=("matching",),
                value_concepts=("omiryn",),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        allow_additional_operations=True,
        tags=("memory_v3", "semantic", "profile", "work"),
    ),
    MemoryV3Scenario(
        id="capture_partner_location_preference",
        description="A dating preference may be personal context, not friend matching data.",
        messages=(
            {
                "role": "user",
                "content": "I want to date someone from Tamil Nadu, ideally near Chennai.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("personalization",),
                forbidden_purposes=("matching",),
                value_concepts=("tamil nadu", "chennai"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "semantic", "personalization", "partner_preference"),
        allowed_vibe_areas=(),
    ),
    MemoryV3Scenario(
        id="capture_friend_preference_for_matching",
        description="An explicit friend preference is matching knowledge.",
        messages=(
            {"role": "user", "content": "I get along best with friends who enjoy dry humor."},
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("matching",),
                value_concepts=("friend", "dry humor"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "semantic", "matching", "friend_preference"),
    ),
    MemoryV3Scenario(
        id="capture_lived_trip_as_episode",
        description="A concrete lived event should be episodic rather than a vague stable fact.",
        messages=(
            {"role": "user", "content": "I visited Bengaluru for my college reunion last year."},
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="episodic",
                required_purposes=("personalization",),
                value_concepts=("bengaluru", "reunion"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "episodic", "personalization", "event"),
    ),
    MemoryV3Scenario(
        id="capture_relationship_experience_without_matching_inference",
        description="A past relationship experience helps personal context but is not automatically a partner filter.",
        messages=(
            {
                "role": "user",
                "content": "My ex and I often avoided difficult conversations until they became arguments.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="relationship",
                required_purposes=("personalization",),
                forbidden_purposes=("matching",),
                value_concepts=("avoided", "arguments"),
                evidence_message_indexes=(0,),
                sensitivity="sensitive",
            ),
        ),
        tags=("memory_v3", "relationship", "personalization", "sensitivity"),
    ),
    MemoryV3Scenario(
        id="capture_companion_interaction_preference",
        description="An explicit request about how the companion should talk is procedural memory.",
        messages=(
            {
                "role": "user",
                "content": "Please ask me fewer questions and share your own thoughts too.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="procedural",
                required_purposes=("personalization",),
                value_concepts=("question", "thought"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "procedural", "personalization", "conversation_style"),
    ),
    MemoryV3Scenario(
        id="use_previous_batch_context_without_old_evidence",
        description="Prior context may resolve meaning, but only the new user message may support the memory.",
        messages=(
            {"role": "user", "content": "I want a friend who makes difficult days lighter."},
            {"role": "assistant", "content": "What does that look like to you?"},
            {"role": "user", "content": "Calm and funny, but not loud."},
        ),
        processed_through_message_index=1,
        previous_handoff=MemoryHandoff(active_topics=("friend compatibility",)),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("matching",),
                value_concepts=("calm", "funny"),
                evidence_message_indexes=(2,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "cross_batch", "semantic", "matching"),
    ),
    MemoryV3Scenario(
        id="ignore_incidental_technical_subject",
        description="A technical subject being discussed is not a fact or preference about the user.",
        messages=({"role": "user", "content": "Can you explain how Python decorators work?"},),
        expected_decision="no_change",
        tags=("memory_v3", "incidental_content", "no_change"),
    ),
    MemoryV3Scenario(
        id="reject_assistant_claim_and_capture_user_correction",
        description="Assistant guesses are not evidence; an explicit user correction may be memory.",
        messages=(
            {"role": "assistant", "content": "You probably love hiking alone."},
            {"role": "user", "content": "No, I prefer team sports."},
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("profile",),
                forbidden_purposes=("matching",),
                value_concepts=("team", "sports"),
                evidence_message_indexes=(1,),
                sensitivity="standard",
            ),
        ),
        forbidden_concepts=("hiking",),
        tags=("memory_v3", "assistant_contamination", "semantic", "profile"),
    ),
    MemoryV3Scenario(
        id="reinforce_existing_preference_without_duplicate",
        description="Repeated evidence should reinforce an equivalent active memory.",
        messages=(
            {"role": "user", "content": "Toyota Hilux and Fortuner are still my favourite cars."},
        ),
        existing_memories=(
            ExistingMemoryV3Fixture(
                id="cars-memory",
                memory_kind="semantic",
                purposes=("profile",),
                key="favorite_cars",
                value=["Toyota Hilux", "Toyota Fortuner"],
            ),
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="reinforce",
                target_memory_id="cars-memory",
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_v3", "lifecycle", "reinforce", "deduplication"),
    ),
    MemoryV3Scenario(
        id="supersede_corrected_location",
        description="An explicit move should supersede the prior current location.",
        messages=({"role": "user", "content": "I moved from Mumbai to Hyderabad last month."},),
        existing_memories=(
            ExistingMemoryV3Fixture(
                id="location-memory",
                memory_kind="semantic",
                purposes=("profile",),
                key="current_location",
                value="Mumbai",
            ),
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="supersede",
                memory_kind="semantic",
                required_purposes=("profile",),
                target_memory_id="location-memory",
                value_concepts=("hyderabad",),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "lifecycle", "supersede", "correction"),
    ),
    MemoryV3Scenario(
        id="retract_withdrawn_preference",
        description="A withdrawn preference should be retracted when no replacement is supplied.",
        messages=(
            {
                "role": "user",
                "content": "Remove my Bengaluru-only dating preference. Location no longer matters.",
            },
        ),
        existing_memories=(
            ExistingMemoryV3Fixture(
                id="partner-location-memory",
                memory_kind="semantic",
                purposes=("personalization",),
                key="preferred_partner_location",
                value="Bengaluru",
            ),
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="retract",
                target_memory_id="partner-location-memory",
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_v3", "lifecycle", "retract", "correction"),
    ),
    MemoryV3Scenario(
        id="ignore_incidental_repeat_of_retracted_memory",
        description="A rejected memory remains history and is not recreated from related conversation.",
        messages=(
            {
                "role": "user",
                "content": "Pune has plenty of popular weekend hiking routes.",
            },
        ),
        existing_memories=(
            ExistingMemoryV3Fixture(
                id="retracted-weekend-memory",
                memory_kind="semantic",
                purposes=("personalization",),
                key="preferred_partner_activity",
                value="enjoys weekend hikes together",
                status="retracted",
            ),
        ),
        expected_decision="no_change",
        tags=("memory_v3", "lifecycle", "retraction_history", "no_change"),
    ),
    MemoryV3Scenario(
        id="explicitly_renew_retracted_preference",
        description="An explicit reversal creates a fresh evidence-backed memory instead of reviving history.",
        messages=(
            {
                "role": "user",
                "content": (
                    "I rejected this before, but that was a mistake: I do want a partner "
                    "who enjoys weekend hikes with me."
                ),
            },
        ),
        existing_memories=(
            ExistingMemoryV3Fixture(
                id="retracted-weekend-memory",
                memory_kind="semantic",
                purposes=("personalization",),
                key="preferred_partner_activity",
                value="enjoys weekend hikes together",
                status="retracted",
            ),
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("personalization",),
                forbidden_purposes=("matching",),
                value_concepts=("partner", "weekend", "hike"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "lifecycle", "retraction_history", "explicit_reversal"),
    ),
    MemoryV3Scenario(
        id="preserve_specific_work_activity_without_job_inference",
        description="Work activity should remain specific without inventing an occupation.",
        messages=(
            {"role": "user", "content": "At work I design backend systems and mentor two engineers."},
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("profile",),
                forbidden_purposes=("matching",),
                value_concepts=("backend", "mentor"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "semantic", "profile", "specific_value", "work"),
    ),
    MemoryV3Scenario(
        id="preserve_relationship_participants_pattern_and_outcome",
        description="Relationship memory should retain participants, behavior, and outcome.",
        messages=(
            {
                "role": "user",
                "content": "My former roommate and I avoided money talks, so small bills became arguments.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="relationship",
                required_purposes=("personalization",),
                forbidden_purposes=("matching",),
                value_concepts=("roommate", "money", "arguments"),
                evidence_message_indexes=(0,),
                sensitivity="sensitive",
            ),
        ),
        tags=("memory_v3", "relationship", "personalization", "specific_value"),
    ),
    MemoryV3Scenario(
        id="keep_friend_preference_semantic_and_specific",
        description="A friend preference is semantic matching knowledge, not procedure.",
        messages=(
            {
                "role": "user",
                "content": "I connect best with friends who are curious and can disagree gently.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("matching",),
                value_concepts=("curious", "disagree", "gently"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "semantic", "matching", "specific_value"),
    ),
    MemoryV3Scenario(
        id="preserve_episode_activity_place_and_subject",
        description="An episode should retain the concrete event rather than a vague topic.",
        messages=(
            {
                "role": "user",
                "content": "During my Jaipur trip I spent a morning volunteering with rescue dogs.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="episodic",
                required_purposes=("personalization",),
                value_concepts=("jaipur", "volunteering", "dogs"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "episodic", "personalization", "specific_value"),
    ),
    MemoryV3Scenario(
        id="ignore_quoted_third_party_preference",
        description="A quoted preference belongs to its speaker and must not become the user's memory.",
        messages=(
            {
                "role": "user",
                "content": 'My friend said, "I only date doctors." What do you think about that?',
            },
        ),
        expected_decision="no_change",
        tags=("memory_v3", "admission_quality", "attribution", "no_change"),
    ),
    MemoryV3Scenario(
        id="ignore_hypothetical_self_description",
        description="A conditional possibility is not durable knowledge about the user.",
        messages=(
            {
                "role": "user",
                "content": "If I moved to Goa someday, I might want someone who loves beaches.",
            },
        ),
        expected_decision="no_change",
        tags=("memory_v3", "admission_quality", "hypothetical", "no_change"),
    ),
    MemoryV3Scenario(
        id="ignore_transient_task_content",
        description="Content requested for a temporary task is not a user fact or preference.",
        messages=({"role": "user", "content": "For this example, print hello world in Python."},),
        expected_decision="no_change",
        tags=("memory_v3", "admission_quality", "task_content", "no_change"),
    ),
    MemoryV3Scenario(
        id="ignore_ambiguous_acknowledgement",
        description="A tentative reaction to an assistant inference does not confirm that inference.",
        messages=(
            {"role": "assistant", "content": "It sounds like you prefer adventurous people."},
            {"role": "user", "content": "Maybe, I guess."},
        ),
        expected_decision="no_change",
        tags=("memory_v3", "admission_quality", "uncertainty", "no_change"),
    ),
    MemoryV3Scenario(
        id="capture_explicit_durable_preference",
        description="A clear durable friend preference is useful matching memory.",
        messages=(
            {
                "role": "user",
                "content": "I want close friends who respect a no and keep plans they make with me.",
            },
        ),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("matching",),
                value_concepts=("friends", "respect", "plans"),
                evidence_message_indexes=(0,),
                sensitivity="standard",
            ),
        ),
        tags=("memory_v3", "admission_quality", "matching", "explicit_preference"),
    ),
    MemoryV3Scenario(
        id="classify_explicit_medical_fact_as_highly_sensitive",
        description="If an explicit medical fact is stored, it must carry the strongest sensitivity class.",
        messages=({"role": "user", "content": "I have a severe peanut allergy."},),
        expected_operations=(
            ExpectedMemoryV3Operation(
                operation="add",
                memory_kind="semantic",
                required_purposes=("profile",),
                value_concepts=("peanut", "allergy"),
                evidence_message_indexes=(0,),
                sensitivity="highly_sensitive",
            ),
        ),
        tags=("memory_v3", "semantic", "profile", "sensitivity"),
    ),
    MemoryV3Scenario(
        id="vibe_small_talk_fills_nothing",
        description="Greetings and one-word replies say nothing about the user's friend vibe.",
        messages=(
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hey! What's going on today?"},
            {"role": "user", "content": "nothing much"},
            {"role": "assistant", "content": "A slow day then. Those are underrated."},
            {"role": "user", "content": "yeah"},
        ),
        allowed_vibe_areas=(),
        grade_memory_operations=False,
        tags=("memory_v3", "vibe", "grounding"),
    ),
    MemoryV3Scenario(
        id="vibe_only_what_the_user_showed",
        description="The user shows their humor; the companion's own views on friendship are not the user's.",
        messages=(
            {"role": "assistant", "content": "Honestly I think loyalty is everything in a friend. Flaky people are the worst."},
            {"role": "user", "content": "lol maybe. I just need someone who gets sarcasm, I can't do people who take every joke literally"},
            {"role": "assistant", "content": "Ha, so deadpan or nothing."},
            {"role": "user", "content": "exactly, slapstick stuff is so cringe to me"},
        ),
        allowed_vibe_areas=("humor", "friend_wish", "deal_breakers"),
        required_vibe_areas=("humor",),
        grade_memory_operations=False,
        tags=("memory_v3", "vibe", "grounding"),
    ),
    MemoryV3Scenario(
        id="vibe_leaves_out_health_and_partner_preferences",
        description="Health details and dating dealbreakers are not friend vibe; only the friend line counts.",
        messages=(
            {"role": "user", "content": "I have bipolar disorder btw, been managing it for years"},
            {"role": "assistant", "content": "Thanks for telling me. Years of managing it takes real work."},
            {"role": "user", "content": "yeah. and for dating, smoking is a hard no for me"},
            {"role": "assistant", "content": "Clear line. What about friends, anything like that?"},
            {"role": "user", "content": "friends can smoke, whatever. I just can't stand friends who cancel last minute"},
        ),
        allowed_vibe_areas=("deal_breakers", "accepts"),
        required_vibe_areas=("deal_breakers",),
        grade_memory_operations=False,
        tags=("memory_v3", "vibe", "grounding", "sensitivity"),
    ),
    MemoryV3Scenario(
        id="vibe_filler_phrases_fill_nothing",
        description="Hinglish filler and a passing mood do not show humor, social energy or how they keep in touch.",
        messages=(
            {"role": "assistant", "content": "Kya chal raha hai aaj?"},
            {"role": "user", "content": "pata nahi yaar"},
            {"role": "assistant", "content": "Ek woh din hai, haan?"},
            {"role": "user", "content": "bas chill karo"},
            {"role": "assistant", "content": "Done, chill mode on."},
            {"role": "user", "content": "ok kal baat karenge"},
        ),
        allowed_vibe_areas=(),
        grade_memory_operations=False,
        tags=("memory_v3", "vibe", "grounding"),
    ),
    MemoryV3Scenario(
        id="vibe_companion_opinion_is_not_the_user",
        description="The companion shares views on friends and politics; the user only reacts, so nothing is learned.",
        messages=(
            {"role": "assistant", "content": "Hot take: friends who talk politics all the time are exhausting. And I'd pick a small group over a party any day."},
            {"role": "user", "content": "haha ok"},
            {"role": "assistant", "content": "You're allowed to disagree, you know."},
            {"role": "user", "content": "hmm"},
        ),
        allowed_vibe_areas=(),
        grade_memory_operations=False,
        tags=("memory_v3", "vibe", "grounding"),
    ),
)


def list_memory_v3_scenarios(*, tags: tuple[str, ...] = ()) -> tuple[MemoryV3Scenario, ...]:
    """Return all v3 cases or those containing every requested tag."""
    required = set(tags)
    return tuple(scenario for scenario in MEMORY_V3_SCENARIOS if required.issubset(scenario.tags))


def get_memory_v3_scenario(scenario_id: str) -> MemoryV3Scenario:
    """Resolve one v3 scenario by its stable command-line id."""
    for scenario in MEMORY_V3_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise ValueError(f"Unknown v3 memory scenario: {scenario_id}")


__all__ = [
    "ExistingMemoryV3Fixture",
    "ExpectedMemoryV3Operation",
    "MEMORY_V3_SCENARIOS",
    "MemoryV3Scenario",
    "get_memory_v3_scenario",
    "list_memory_v3_scenarios",
]
