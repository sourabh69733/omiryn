"""Thread-management evaluation cases; runners consume these without changing live state."""

from __future__ import annotations

from dataclasses import dataclass


THREAD_OPERATIONS = frozenset(
    {"create", "continue", "switch", "pause", "complete", "block"}
)
THREAD_STATUSES = frozenset({"open", "paused", "completed", "blocked_by_user"})


@dataclass(frozen=True)
class ExistingThreadFixture:
    """Minimal persisted-thread state required to prepare one evaluation case."""

    id: str
    title: str
    summary: str
    status: str = "open"
    active: bool = False
    from_previous_conversation: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.title.strip() or not self.summary.strip():
            raise ValueError("Thread fixtures require an id, title, and summary.")
        if self.status not in THREAD_STATUSES:
            raise ValueError(f"Unsupported thread fixture status: {self.status}")
        if self.active and self.status != "open":
            raise ValueError("Only an open thread can be active.")


@dataclass(frozen=True)
class ExpectedThreadAction:
    """Observable model action expected from a scenario, without prescribing its wording."""

    operation: str
    thread_id: str | None = None
    title_concepts: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.operation not in THREAD_OPERATIONS:
            raise ValueError(f"Unsupported expected thread operation: {self.operation}")
        if self.operation == "create":
            if self.thread_id is not None:
                raise ValueError("A create expectation cannot reference an existing thread.")
            if not self.title_concepts:
                raise ValueError("A create expectation needs semantic title concepts.")
        elif not self.thread_id:
            raise ValueError(f"{self.operation} requires an existing thread id.")
        if not self.reason.strip():
            raise ValueError("Expected thread actions require a human-readable reason.")


@dataclass(frozen=True)
class ThreadManagementScenario:
    """Conversation input and expected shadow proposal for thread intelligence evaluation."""

    id: str
    description: str
    prior_messages: tuple[dict[str, str], ...]
    user_message: str
    existing_threads: tuple[ExistingThreadFixture, ...] = ()
    expected_action: ExpectedThreadAction | None = None
    tags: tuple[str, ...] = ("thread_management_v1",)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.description.strip() or not self.user_message.strip():
            raise ValueError("Thread scenarios require an id, description, and user message.")
        if any(message.get("role") not in {"user", "assistant"} for message in self.prior_messages):
            raise ValueError(f"Thread scenario '{self.id}' contains an unsupported message role.")
        if any(not str(message.get("content", "")).strip() for message in self.prior_messages):
            raise ValueError(f"Thread scenario '{self.id}' contains an empty message.")
        thread_ids = [thread.id for thread in self.existing_threads]
        if len(thread_ids) != len(set(thread_ids)):
            raise ValueError(f"Thread scenario '{self.id}' contains duplicate thread ids.")
        if sum(thread.active for thread in self.existing_threads) > 1:
            raise ValueError(f"Thread scenario '{self.id}' has more than one active thread.")
        if (
            self.expected_action is not None
            and self.expected_action.thread_id is not None
            and self.expected_action.thread_id not in set(thread_ids)
        ):
            raise ValueError(
                f"Thread scenario '{self.id}' expects an unknown thread id: "
                f"{self.expected_action.thread_id}"
            )


THREAD_MANAGEMENT_SCENARIOS = (
    ThreadManagementScenario(
        id="create_meaningful_personal_thread",
        description="A durable personal subject should become a new resumable thread.",
        prior_messages=(
            {"role": "assistant", "content": "What has been taking most of your energy lately?"},
        ),
        user_message=(
            "My manager keeps changing priorities and blaming me when deadlines slip. "
            "It has been happening for months."
        ),
        expected_action=ExpectedThreadAction(
            operation="create",
            title_concepts=("manager", "work"),
            reason="The user introduced a meaningful, ongoing subject worth resuming later.",
        ),
        tags=("thread_management_v1", "create", "user_started"),
    ),
    ThreadManagementScenario(
        id="ignore_light_greeting",
        description="Short-lived social talk should not create a persistent thread.",
        prior_messages=(),
        user_message="Hey, how are you?",
        expected_action=None,
        tags=("thread_management_v1", "none", "random_talk"),
    ),
    ThreadManagementScenario(
        id="ignore_transient_small_talk_inside_active_thread",
        description="A passing greeting should not create or mutate a meaningful active thread.",
        prior_messages=(
            {"role": "assistant", "content": "Good morning. How is your day starting?"},
        ),
        user_message="Fine, just having chai before work.",
        existing_threads=(
            ExistingThreadFixture(
                id="career-thread",
                title="Career change",
                summary="The user is considering moving into product design.",
                active=True,
            ),
        ),
        expected_action=None,
        tags=("thread_management_v1", "none", "random_talk", "active_thread"),
    ),
    ThreadManagementScenario(
        id="continue_active_thread",
        description="A new message about the active subject should continue that thread.",
        prior_messages=(
            {"role": "assistant", "content": "What worries you most about changing careers?"},
        ),
        user_message="Mostly losing stability while I learn product design.",
        existing_threads=(
            ExistingThreadFixture(
                id="career-thread",
                title="Career change",
                summary="The user is considering moving into product design.",
                active=True,
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="continue",
            thread_id="career-thread",
            reason="The message directly develops the active career-change subject.",
        ),
        tags=("thread_management_v1", "continue", "active_thread"),
    ),
    ThreadManagementScenario(
        id="switch_to_existing_open_thread",
        description="The model should switch to the relevant existing thread instead of duplicating it.",
        prior_messages=(
            {"role": "assistant", "content": "Do you still want to talk through the job offer?"},
        ),
        user_message="Later. I finally booked the Goa trip we were discussing.",
        existing_threads=(
            ExistingThreadFixture(
                id="career-thread",
                title="Job offer",
                summary="The user is deciding whether to accept a new job.",
                active=True,
            ),
            ExistingThreadFixture(
                id="goa-thread",
                title="Goa trip",
                summary="The user was planning a trip to Goa with friends.",
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="switch",
            thread_id="goa-thread",
            reason="The user explicitly moves from the active subject to another known subject.",
        ),
        tags=("thread_management_v1", "switch", "deduplication"),
    ),
    ThreadManagementScenario(
        id="pause_unfinished_thread",
        description="A temporary request to leave a subject should pause, not complete or block, it.",
        prior_messages=(
            {"role": "assistant", "content": "We can unpack what happened with your sister."},
        ),
        user_message="Let's leave this for now. Maybe we can continue another day.",
        existing_threads=(
            ExistingThreadFixture(
                id="sister-thread",
                title="Conflict with sister",
                summary="The user is hurt by a recent argument with their sister.",
                active=True,
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="pause",
            thread_id="sister-thread",
            reason="The user permits a later return but does not want to continue now.",
        ),
        tags=("thread_management_v1", "pause", "temporary_boundary"),
    ),
    ThreadManagementScenario(
        id="complete_resolved_thread",
        description="A clearly resolved subject should be completed rather than left open.",
        prior_messages=(
            {"role": "assistant", "content": "How did the conversation with your manager go?"},
        ),
        user_message="We sorted it out and agreed on priorities. That issue is finished now.",
        existing_threads=(
            ExistingThreadFixture(
                id="manager-thread",
                title="Conflict with manager",
                summary="Changing priorities caused conflict between the user and their manager.",
                active=True,
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="complete",
            thread_id="manager-thread",
            reason="The user explicitly says the underlying issue has been resolved.",
        ),
        tags=("thread_management_v1", "complete", "resolution"),
    ),
    ThreadManagementScenario(
        id="block_thread_after_explicit_boundary",
        description="A firm no-return boundary must permanently block the relevant thread.",
        prior_messages=(
            {"role": "assistant", "content": "Did the breakup change what you want next?"},
        ),
        user_message="I don't want you to bring up my breakup again.",
        existing_threads=(
            ExistingThreadFixture(
                id="breakup-thread",
                title="Past breakup",
                summary="The user previously discussed the end of a relationship.",
                active=True,
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="block",
            thread_id="breakup-thread",
            reason="The user explicitly forbids the agent from returning to the subject.",
        ),
        tags=("thread_management_v1", "block", "user_boundary"),
    ),
    ThreadManagementScenario(
        id="continue_semantically_same_thread_without_duplicate",
        description="Different wording for the same subject should continue the existing thread.",
        prior_messages=(),
        user_message="I am still unsure whether relocating to Bengaluru is worth it.",
        existing_threads=(
            ExistingThreadFixture(
                id="move-thread",
                title="Possible move to Bengaluru",
                summary="The user is weighing a relocation to Bengaluru for work.",
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="continue",
            thread_id="move-thread",
            reason="Relocating and moving to Bengaluru refer to the same durable subject.",
        ),
        tags=("thread_management_v1", "continue", "deduplication"),
    ),
    ThreadManagementScenario(
        id="resume_thread_from_previous_conversation",
        description="A known unfinished subject should resume across conversation sessions.",
        prior_messages=(),
        user_message="Remember that issue with my manager? It got worse today.",
        existing_threads=(
            ExistingThreadFixture(
                id="old-manager-thread",
                title="Stress with manager",
                summary="The user's manager frequently changes plans and causes stress.",
                from_previous_conversation=True,
            ),
        ),
        expected_action=ExpectedThreadAction(
            operation="continue",
            thread_id="old-manager-thread",
            reason="The user deliberately resumes an unfinished subject from an earlier session.",
        ),
        tags=("thread_management_v1", "continue", "cross_session"),
    ),
)


def list_thread_management_scenarios(
    *,
    tags: tuple[str, ...] = (),
) -> tuple[ThreadManagementScenario, ...]:
    """Return every case containing all requested tags."""
    if not tags:
        return THREAD_MANAGEMENT_SCENARIOS
    required = {tag.strip().casefold() for tag in tags if tag.strip()}
    return tuple(
        scenario
        for scenario in THREAD_MANAGEMENT_SCENARIOS
        if required.issubset({tag.casefold() for tag in scenario.tags})
    )


def get_thread_management_scenario(scenario_id: str) -> ThreadManagementScenario:
    """Resolve a scenario by stable command-line-friendly identifier."""
    for scenario in THREAD_MANAGEMENT_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    available = ", ".join(scenario.id for scenario in THREAD_MANAGEMENT_SCENARIOS)
    raise ValueError(f"Unknown thread scenario '{scenario_id}'. Available: {available}")
