"""Verifies foreground planning decisions made from persistent thread state."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.contracts.models import (
    ContextQueryIntent,
    ConversationalStance,
    EmotionState,
    ThreadGuidance,
    ThreadReference,
)
from agent.context_engine.conversation_engine.planning import build_conversation_plan
from agent.context_engine.conversation_engine.state import (
    ConversationState,
    create_thread,
    save_state,
)
from storage import reset_db, save_conversation


class ThreadForegroundGuidanceTest(unittest.TestCase):
    def test_low_information_continues_an_engaged_active_thread(self) -> None:
        plan = self._plan(
            intent=ContextQueryIntent(labels=("low_information",), is_low_information=True),
            guidance=ThreadGuidance(
                active=self._thread(
                    thread_id="active-career",
                    origin="user_started",
                    user_interest="high",
                )
            ),
        )

        self.assertEqual(plan.thread_action, "continue_active")
        self.assertEqual(plan.thread_id, "active-career")
        self.assertEqual(plan.thread_title, "Career change")

    def test_unaccepted_agent_started_thread_is_not_pushed(self) -> None:
        plan = self._plan(
            intent=ContextQueryIntent(labels=("low_information",), is_low_information=True),
            guidance=ThreadGuidance(
                active=self._thread(
                    thread_id="agent-first-love",
                    origin="agent_started",
                    user_interest="unknown",
                )
            ),
        )

        self.assertEqual(plan.thread_action, "ignore_unengaged")
        self.assertEqual(plan.thread_id, "agent-first-love")

    def test_user_constraint_suppresses_thread_continuation(self) -> None:
        plan = self._plan(
            intent=ContextQueryIntent(labels=("low_information",), is_low_information=True),
            stance=ConversationalStance(
                mode="neutral",
                constraints=("give_space",),
            ),
            guidance=ThreadGuidance(
                active=self._thread(
                    thread_id="active-career",
                    origin="user_started",
                    user_interest="high",
                )
            ),
        )

        self.assertEqual(plan.thread_action, "follow_user")
        self.assertIsNone(plan.thread_id)

    def test_substantive_user_message_has_priority_over_active_thread(self) -> None:
        plan = self._plan(
            intent=ContextQueryIntent(labels=("general_chat",), is_low_information=False),
            guidance=ThreadGuidance(
                active=self._thread(
                    thread_id="active-career",
                    origin="user_started",
                    user_interest="high",
                )
            ),
        )

        self.assertEqual(plan.thread_action, "follow_user")
        self.assertIsNone(plan.thread_id)

    def test_low_information_can_offer_an_engaged_relevant_open_thread(self) -> None:
        plan = self._plan(
            intent=ContextQueryIntent(labels=("low_information",), is_low_information=True),
            guidance=ThreadGuidance(
                relevant_open=(
                    self._thread(
                        thread_id="open-trip",
                        origin="user_started",
                        user_interest="medium",
                    ),
                )
            ),
        )

        self.assertEqual(plan.thread_action, "offer_open")
        self.assertEqual(plan.thread_id, "open-trip")

    def _plan(
        self,
        *,
        intent: ContextQueryIntent,
        guidance: ThreadGuidance,
        stance: ConversationalStance | None = None,
    ):
        return build_conversation_plan(
            user_text="hmm",
            intent=intent,
            emotion_state=EmotionState(),
            conversational_stance=stance or ConversationalStance(),
            matching_understanding=None,
            thread_guidance=guidance,
            listener_first=True,
        )

    @staticmethod
    def _thread(
        *,
        thread_id: str,
        origin: str,
        user_interest: str,
    ) -> ThreadReference:
        return ThreadReference(
            id=thread_id,
            title="Career change",
            origin=origin,
            user_interest=user_interest,
            next_angle="Ask what kind of work feels meaningful.",
            cross_session=False,
        )


class ThreadForegroundContextIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "foreground-guidance-user"
        self.conversation_id = "foreground-guidance-conversation"
        save_conversation(
            {"id": self.conversation_id, "status": "active", "messages": []},
            self.user_id,
        )

    def test_unaccepted_agent_started_active_thread_is_explicitly_ignored(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            title="First love stories",
            summary="The agent suggested first-love stories but the user did not engage.",
            origin="agent_started",
            user_interest="unknown",
        )
        save_state(
            ConversationState(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                active_thread_id=thread.id,
            )
        )

        with patch.dict(
            "os.environ",
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
        ):
            package = build_model_context_package(
                conversation_id=self.conversation_id,
                user_text="hmm",
                user_id=self.user_id,
                user_profile={"user_id": self.user_id},
                model="mock-model",
                agent_tone="auto",
                agent_name="Omiryn",
                style_source_id=None,
                user_message_index=1,
                assistant_message_index=2,
                prompt_version_id="v3-1",
            )

        plan = package.snapshot["context"]["conversation_plan"]
        self.assertEqual(plan["thread_action"], "ignore_unengaged")
        self.assertEqual(plan["thread_id"], thread.id)
        self.assertIn("Do not revive this subject", package.system_prompt)

    def test_active_thread_reaches_the_foreground_plan_and_prompt(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            title="Career change",
            summary="The user is deciding whether to change careers.",
            origin="user_started",
            user_interest="high",
            next_angle="Explore what meaningful work means to the user.",
        )
        save_state(
            ConversationState(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                state_through_message_index=2,
                active_thread_id=thread.id,
            )
        )

        with patch.dict(
            "os.environ",
            {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
        ):
            package = build_model_context_package(
                conversation_id=self.conversation_id,
                user_text="hmm",
                user_id=self.user_id,
                user_profile={"user_id": self.user_id},
                model="mock-model",
                agent_tone="auto",
                agent_name="Omiryn",
                style_source_id=None,
                user_message_index=3,
                assistant_message_index=4,
                prompt_version_id="v3-1",
            )

        self.assertEqual(package.thread_guidance.active.id, thread.id)
        self.assertEqual(
            package.snapshot["context"]["conversation_plan"]["thread_action"],
            "continue_active",
        )
        self.assertEqual(package.snapshot["summary"]["thread_action"], "continue_active")
        self.assertEqual(package.snapshot["summary"]["thread_id"], thread.id)
        self.assertIn("Thread continuity decision", package.system_prompt)
        self.assertIn("continue_active", package.system_prompt)



if __name__ == "__main__":
    unittest.main()
