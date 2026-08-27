"""Realistic, deterministic cases for evaluating background memory proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.processing import MemoryHandoff


@dataclass(frozen=True)
class ExistingMemoryFixture:
    """One memory supplied to the model so update operations can be evaluated."""

    id: str
    data_point_type: str
    category: str
    key: str
    label: str
    value: Any
    confidence: float = 0.9

    def as_context(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "data_point_type": self.data_point_type,
            "category": self.category,
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ExpectedMemoryOperation:
    """Semantic expectation that tolerates harmless wording differences."""

    operation: str
    data_point_type: str | None = None
    memory_basis: str | None = None
    target_memory_id: str | None = None
    value_concepts: tuple[str, ...] = ()
    evidence_message_indexes: tuple[int, ...] = ()


@dataclass(frozen=True)
class MemoryShadowScenario:
    """A bounded conversation batch and its expected memory behavior."""

    id: str
    description: str
    messages: tuple[dict[str, Any], ...]
    expected_operations: tuple[ExpectedMemoryOperation, ...] = ()
    optional_operations: tuple[ExpectedMemoryOperation, ...] = ()
    expected_decision: str = "propose"
    existing_memories: tuple[ExistingMemoryFixture, ...] = ()
    processed_through_message_index: int = -1
    previous_handoff: MemoryHandoff = field(default_factory=MemoryHandoff)
    forbidden_concepts: tuple[str, ...] = ()
    tags: tuple[str, ...] = ("memory_shadow_v1",)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.description.strip() or not self.messages:
            raise ValueError("Memory scenarios require an id, description, and messages.")
        if self.expected_decision not in {"propose", "no_change"}:
            raise ValueError("Expected decision must be propose or no_change.")
        if self.expected_decision == "no_change" and self.expected_operations:
            raise ValueError("A no_change scenario cannot expect operations.")
        indexes = set(range(len(self.messages)))
        for expected in (*self.expected_operations, *self.optional_operations):
            if not set(expected.evidence_message_indexes).issubset(indexes):
                raise ValueError(f"Scenario '{self.id}' contains an unknown evidence index.")
        memory_ids = {memory.id for memory in self.existing_memories}
        if len(memory_ids) != len(self.existing_memories):
            raise ValueError(f"Scenario '{self.id}' contains duplicate memory ids.")


MEMORY_SHADOW_SCENARIOS = (
    MemoryShadowScenario(
        id="capture_current_location_profile_fact",
        description="A stable current location should become a concrete profile fact.",
        messages=(
            {"role": "assistant", "content": "Where are you based these days?"},
            {"role": "user", "content": "I live in Pune now."},
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="profile_fact",
                memory_basis="stable_user_attribute",
                value_concepts=("pune",),
                evidence_message_indexes=(1,),
            ),
        ),
        tags=("memory_shadow_v1", "profile_fact", "add"),
    ),
    MemoryShadowScenario(
        id="capture_partner_location_preference",
        description="A desired partner location is a matching fact, not the user's location.",
        messages=(
            {
                "role": "user",
                "content": "I want to date someone from Tamil Nadu, ideally near Chennai.",
            },
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="matching_fact",
                memory_basis="explicit_matching_preference",
                value_concepts=("tamil nadu", "chennai"),
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "matching_fact", "partner_preference", "add"),
    ),
    MemoryShadowScenario(
        id="reinforce_existing_car_preference_without_duplicate",
        description="Restating an existing preference should reinforce it instead of duplicating it.",
        messages=(
            {"role": "user", "content": "Toyota Hilux and Fortuner are still my favourite cars."},
        ),
        existing_memories=(
            ExistingMemoryFixture(
                id="cars-memory",
                data_point_type="matching_fact",
                category="vehicles",
                key="favorite_cars",
                label="Favorite cars",
                value=["Toyota Hilux", "Toyota Fortuner"],
            ),
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="reinforce",
                target_memory_id="cars-memory",
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "deduplication", "reinforce"),
    ),
    MemoryShadowScenario(
        id="supersede_corrected_location",
        description="An explicit move should replace the old current-location memory.",
        messages=(
            {"role": "user", "content": "I moved from Mumbai to Hyderabad last month."},
        ),
        existing_memories=(
            ExistingMemoryFixture(
                id="location-memory",
                data_point_type="profile_fact",
                category="location",
                key="current_location",
                label="Lives in Mumbai",
                value="Mumbai",
            ),
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="supersede",
                data_point_type="profile_fact",
                memory_basis="stable_user_attribute",
                target_memory_id="location-memory",
                value_concepts=("hyderabad",),
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "correction", "supersede"),
    ),
    MemoryShadowScenario(
        id="retract_withdrawn_partner_location_filter",
        description="A preference explicitly withdrawn by the user should be retracted.",
        messages=(
            {
                "role": "user",
                "content": "Location no longer matters to me. Remove my Bengaluru-only preference.",
            },
        ),
        existing_memories=(
            ExistingMemoryFixture(
                id="partner-location-memory",
                data_point_type="matching_fact",
                category="partner_location",
                key="preferred_partner_location",
                label="Prefers a partner from Bengaluru",
                value="Bengaluru",
            ),
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="retract",
                target_memory_id="partner-location-memory",
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "correction", "retract"),
    ),
    MemoryShadowScenario(
        id="reject_assistant_claim_and_capture_user_correction",
        description="Assistant guesses must not become memories; the user's correction may.",
        messages=(
            {"role": "assistant", "content": "It sounds like you probably love hiking alone."},
            {"role": "user", "content": "No, I prefer team sports."},
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="matching_fact",
                memory_basis="explicit_matching_preference",
                value_concepts=("team", "sports"),
                evidence_message_indexes=(1,),
            ),
        ),
        forbidden_concepts=("hiking",),
        tags=("memory_shadow_v1", "assistant_contamination", "matching_fact"),
    ),
    MemoryShadowScenario(
        id="use_previous_batch_context_without_using_it_as_evidence",
        description="Old context may resolve meaning, but only the new user message is evidence.",
        messages=(
            {"role": "user", "content": "I want someone who makes difficult days lighter."},
            {"role": "assistant", "content": "What does that look like to you?"},
            {"role": "user", "content": "Calm and funny, but not loud."},
        ),
        processed_through_message_index=1,
        previous_handoff=MemoryHandoff(active_topics=("partner personality",)),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="matching_fact",
                memory_basis="explicit_matching_preference",
                value_concepts=("calm", "funny"),
                evidence_message_indexes=(2,),
            ),
        ),
        tags=("memory_shadow_v1", "cross_batch", "matching_fact"),
    ),
    MemoryShadowScenario(
        id="capture_conversation_style_learning",
        description="How the user wants the companion to converse should become chat learning.",
        messages=(
            {"role": "user", "content": "Please don't ask me a question after every reply."},
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="chat_learning",
                memory_basis="direct_chat_preference",
                value_concepts=("question",),
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "chat_learning", "add"),
    ),
    MemoryShadowScenario(
        id="ignore_short_lived_health_context_without_expiry",
        description="Short-lived context is ignored until it has a real expiry lifecycle.",
        messages=(
            {"role": "user", "content": "I'm sick today, so I'm mostly resting."},
        ),
        expected_decision="no_change",
        tags=("memory_shadow_v1", "temporary_context_rejected", "no_change"),
    ),
    MemoryShadowScenario(
        id="ignore_low_information_acknowledgement",
        description="A simple acknowledgement contains no useful memory.",
        messages=(
            {
                "role": "user",
                "content": "Okay, thanks.",
                "quality": "simple_acknowledgement",
            },
        ),
        expected_decision="no_change",
        tags=("memory_shadow_v1", "no_change", "low_information"),
    ),
    MemoryShadowScenario(
        id="capture_hinglish_partner_personality",
        description="Hinglish wording should preserve the same semantic matching preference.",
        messages=(
            {
                "role": "user",
                "content": "Mujhe calm aur funny ladki pasand hai, bahut loud nahi.",
            },
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="matching_fact",
                memory_basis="explicit_matching_preference",
                value_concepts=("calm", "funny"),
                evidence_message_indexes=(0,),
            ),
        ),
        optional_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="matching_fact",
                memory_basis="explicit_matching_preference",
                value_concepts=("loud",),
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "hinglish", "matching_fact"),
    ),
    MemoryShadowScenario(
        id="ignore_technical_explanation",
        description="A technical explanation is not personal memory.",
        messages=(
            {"role": "user", "content": "A buffer overflow happens when software writes past allocated memory."},
        ),
        expected_decision="no_change",
        tags=("memory_shadow_v1", "memory_eligibility", "technical_content", "no_change"),
    ),
    MemoryShadowScenario(
        id="ignore_code_example",
        description="A code example is not personal memory.",
        messages=(
            {"role": "user", "content": "A basic Python example is print('hello world')."},
        ),
        expected_decision="no_change",
        tags=("memory_shadow_v1", "memory_eligibility", "code_example", "no_change"),
    ),
    MemoryShadowScenario(
        id="ignore_product_name_without_personal_claim",
        description="Merely naming a product does not say anything about the user.",
        messages=(
            {"role": "user", "content": "I was reviewing a product called Omiryn today."},
        ),
        expected_decision="no_change",
        tags=("memory_shadow_v1", "memory_eligibility", "incidental_mention", "no_change"),
    ),
    MemoryShadowScenario(
        id="capture_explicit_work_background_as_profile_fact",
        description="An explicit statement about the user's work belongs in profile facts, never matching facts.",
        messages=(
            {"role": "user", "content": "I build a matchmaking product called Omiryn."},
        ),
        expected_operations=(
            ExpectedMemoryOperation(
                operation="add",
                data_point_type="profile_fact",
                memory_basis="stable_user_attribute",
                value_concepts=("build", "omiryn"),
                evidence_message_indexes=(0,),
            ),
        ),
        tags=("memory_shadow_v1", "memory_eligibility", "profile_fact", "work_background"),
    ),
)


def list_memory_shadow_scenarios(*, tags: tuple[str, ...] = ()) -> tuple[MemoryShadowScenario, ...]:
    """Return the complete catalogue or scenarios containing every requested tag."""
    required = set(tags)
    return tuple(
        scenario for scenario in MEMORY_SHADOW_SCENARIOS if required.issubset(scenario.tags)
    )


def get_memory_shadow_scenario(scenario_id: str) -> MemoryShadowScenario:
    """Resolve an exact scenario id and fail clearly for command-line use."""
    for scenario in MEMORY_SHADOW_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise ValueError(f"Unknown memory shadow scenario: {scenario_id}")


__all__ = [
    "ExistingMemoryFixture",
    "ExpectedMemoryOperation",
    "MEMORY_SHADOW_SCENARIOS",
    "MemoryShadowScenario",
    "get_memory_shadow_scenario",
    "list_memory_shadow_scenarios",
]
