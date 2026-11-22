"""The look-up step: a small model plans the searches, code runs them, the reply model reads the results."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.lookup import PlannedSearch, lookup_plan_input, planned_searches
from agent.providers.extraction import service
from agent.providers.shared.errors import AgentProviderError
from agent.runtime.steps.job import ReplyJob
from agent.runtime.steps.lookup import look_up
from agent.tools import ToolResult

ON = {"TAVILY_API_KEY": "k", "AGENT_LOOKUP_STEP": "true", "AGENT_LOOKUP_MAX_SEARCHES": "2"}
PLAN = {"lookup": True, "searches": [{"query": "TCS fresher salary 2026 India", "recent_days": None}]}
FOUND = "TCS Ninja 3.36 LPA (example.com, Nov 2026)"


def job(text: str = "tcs fresher salary kitni hoti hai", generate=None) -> ReplyJob:
    return ReplyJob([{"role": "user", "content": text}], {}, generate or AsyncMock(), user_id="u1", conversation_id="c1", user_text=text)


async def found(calls, context):
    return [ToolResult(FOUND, {"tool": call.name, "ok": True, "results": 1}) for call in calls]


class PlanTest(unittest.TestCase):
    def test_the_plan_is_read_and_cleaned(self) -> None:
        raw = {"lookup": True, "searches": [{"query": "  GSoC 2027   timeline ", "recent_days": 7}, {"query": "gsoc 2027 timeline"}, {"query": ""}, "GRE required fall 2027 MS", {"query": "x", "recent_days": "soon"}]}
        self.assertEqual(planned_searches(raw, 5), [PlannedSearch("GSoC 2027 timeline", 7), PlannedSearch("GRE required fall 2027 MS"), PlannedSearch("x")])
        self.assertEqual(len(planned_searches(raw, 2)), 2)

    def test_no_lookup_or_a_broken_answer_means_no_search(self) -> None:
        for raw in ({"lookup": False, "searches": [{"query": "x"}]}, {"searches": [{"query": "x"}]}, {}, None, "yes", {"lookup": True, "searches": None}):
            with self.subTest(raw=raw):
                self.assertEqual(planned_searches(raw), [])

    def test_the_planner_reads_the_message_the_date_and_the_place(self) -> None:
        history = [{"role": "user", "content": "gate dena hai"}, {"role": "assistant", "content": "achha"}, {"role": "system", "content": "note"}]
        read = json.loads(lookup_plan_input("uska form kab aayega", history, today="Monday, 23 November 2026", place="Bhopal, India"))
        self.assertEqual(read, {"today": "Monday, 23 November 2026", "place": "Bhopal, India", "recent": ["user: gate dena hai", "assistant: achha"], "message": "uska form kab aayega"})

    def test_a_search_becomes_web_search_arguments(self) -> None:
        self.assertEqual(PlannedSearch("a").arguments, {"query": "a"})
        self.assertEqual(PlannedSearch("a", 7).arguments, {"query": "a", "recent_days": 7})


class LookUpStepTest(unittest.IsolatedAsyncioTestCase):
    async def test_what_was_found_joins_what_the_reply_model_reads(self) -> None:
        with patch.dict(os.environ, ON), patch("agent.runtime.steps.lookup.plan_lookup", AsyncMock(return_value=PLAN)), patch("agent.tools.loop.run_calls", found):
            after, info = await look_up(job(), place="Bhopal, India")

        self.assertEqual([message["role"] for message in after.reply_messages], ["user", "assistant", "tool"])
        self.assertEqual(after.reply_messages[1]["tool_calls"][0]["name"], "web_search")
        self.assertEqual(after.reply_messages[1]["tool_calls"][0]["id"], after.reply_messages[2]["tool_call_id"])
        self.assertTrue(after.reply_messages[2]["tool_call_id"].startswith("lookup_"))
        self.assertEqual(after.reply_messages[2]["content"], FOUND)
        self.assertEqual((info["planned"], info["searches"]), (True, 1))
        self.assertNotIn("salary", json.dumps(info))  # no message text or query in the trace

    async def test_a_rewrite_reads_it_too(self) -> None:
        seen = []

        async def generate(messages, **kwargs):
            seen.append([message["role"] for message in messages])
            return "ok"

        with patch.dict(os.environ, ON), patch("agent.runtime.steps.lookup.plan_lookup", AsyncMock(return_value=PLAN)), patch("agent.tools.loop.run_calls", found):
            after, _ = await look_up(job(generate=generate))
        await after.rewrite("Rewrite needed: say less.")
        self.assertEqual(seen, [["user", "assistant", "tool", "system"]])

    async def test_nothing_to_look_up_leaves_the_turn_as_it_was(self) -> None:
        before = job("aaj mann nahi lag raha")
        with patch.dict(os.environ, ON), patch("agent.runtime.steps.lookup.plan_lookup", AsyncMock(return_value={"lookup": False, "searches": []})):
            after, info = await look_up(before)
        self.assertIs(after, before)
        self.assertEqual((info["planned"], info["searches"]), (True, 0))

    async def test_a_failing_plan_or_search_never_stops_the_reply(self) -> None:
        before = job()
        with patch.dict(os.environ, ON), patch("agent.runtime.steps.lookup.plan_lookup", AsyncMock(side_effect=AgentProviderError("HTTP 429"))):
            after, info = await look_up(before)
        self.assertIs(after, before)
        self.assertEqual((info["planned"], info["error"]), (False, "AgentProviderError"))

        with patch.dict(os.environ, ON), patch("agent.runtime.steps.lookup.plan_lookup", AsyncMock(return_value=PLAN)), patch("agent.tools.loop.run_calls", AsyncMock(side_effect=RuntimeError("down"))):
            after, info = await look_up(before)
        self.assertIs(after, before)
        self.assertEqual(info["error"], "RuntimeError")

    async def test_off_unless_switched_on_and_for_a_greeting(self) -> None:
        planner = AsyncMock(return_value=PLAN)
        with patch("agent.runtime.steps.lookup.plan_lookup", planner):
            with patch.dict(os.environ, {**ON, "TAVILY_API_KEY": ""}):
                self.assertEqual((await look_up(job()))[1], None)
            with patch.dict(os.environ, {**ON, "AGENT_LOOKUP_STEP": ""}):
                self.assertEqual((await look_up(job()))[1], None)  # off by default
            with patch.dict(os.environ, ON):
                self.assertEqual((await look_up(job("hi")))[1], None)
        planner.assert_not_awaited()


class PlanModelTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_refused_model_hands_over_to_the_next(self) -> None:
        tried = []

        async def chat(**kwargs):
            tried.append(kwargs["model"])
            if len(tried) == 1:
                raise AgentProviderError("deepinfra returned HTTP 429")
            return json.dumps(PLAN)

        with patch.dict(os.environ, {"LOOKUP_MODELS": "model-a, model-b"}), patch.object(service, "_provider_name", return_value="deepinfra"), patch.object(service, "provider_chat", chat):
            plan = await service.plan_lookup("{}", conversation_id="c1")

        self.assertEqual(tried, ["model-a", "model-b"])
        self.assertEqual(plan, PLAN)

    def test_any_provider_has_a_model_to_plan_with(self) -> None:
        with patch.dict(os.environ, {"LOOKUP_MODELS": ""}):
            self.assertEqual(service.lookup_models("some-other-provider"), [None])  # the provider's own model
            self.assertEqual(len(service.lookup_models("deepinfra")), 2)


if __name__ == "__main__":
    unittest.main()
