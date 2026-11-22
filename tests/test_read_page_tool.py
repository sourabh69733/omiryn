"""read_page: reads one public web page through the extract service; a pasted link is read before the draft."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from agent.runtime.steps.job import ReplyJob
from agent.runtime.steps.links import read_pasted_links
from agent.tools import ToolCall, ToolContext, ToolResult, run_calls, tool_specs
from agent.tools.read_page import PAGE_CHARS, links_in, public_address

CONTEXT = ToolContext(user_id=None)
ON = {"TAVILY_API_KEY": "k", "AGENT_READ_PAGE": "true", "AGENT_READ_PASTED_LINKS": "true"}
GATE = "https://en.wikipedia.org/wiki/Graduate_Aptitude_Test_in_Engineering"


def _client(handler):
    real = httpx.AsyncClient
    return lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)


def _page(text: str, title: str = "GATE"):
    return lambda request: httpx.Response(200, json={"results": [{"url": GATE, "title": title, "raw_content": text}], "failed_results": []})


class ReadPageToolTest(unittest.IsolatedAsyncioTestCase):
    def test_on_only_with_a_key(self) -> None:
        names = lambda: [spec["function"]["name"] for spec in tool_specs(CONTEXT)]
        with patch.dict(os.environ, {**ON, "TAVILY_API_KEY": ""}):
            self.assertNotIn("read_page", names())
        with patch.dict(os.environ, ON):
            self.assertIn("read_page", names())
        with patch.dict(os.environ, {**ON, "AGENT_READ_PAGE": "false"}):
            self.assertNotIn("read_page", names())

    def test_only_a_public_web_address_is_read(self) -> None:
        self.assertEqual(public_address(f"  {GATE} "), GATE)
        for bad in ("gate exam", "ftp://example.com/x", "file:///etc/passwd", "http://localhost:8000/admin", "http://192.168.1.4/", "http://127.0.0.1/", "http://printer.local/", "https://user:pass@example.com/", "http://intranet/"):
            with self.subTest(bad=bad):
                self.assertIsNone(public_address(bad))

    def test_links_are_found_in_a_message(self) -> None:
        self.assertEqual(links_in(f"ye padh ke bata {GATE}, aur ye bhi (https://x.example/a?b=1). {GATE}"), [GATE, "https://x.example/a?b=1"])
        self.assertEqual(links_in("koi link nahi hai"), [])

    async def test_the_page_text_comes_back_with_how_to_use_it(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"], seen["body"], seen["auth"] = str(request.url), json.loads(request.content), request.headers["authorization"]
            return _page("GATE is an entrance exam.\n\n\n\nIt is held in February.")(request)

        with patch.dict(os.environ, ON), patch("agent.tools.read_page.httpx.AsyncClient", _client(handler)):
            [result] = await run_calls([ToolCall("read_page", {"url": GATE})], CONTEXT)

        self.assertEqual((seen["url"], seen["auth"]), ("https://api.tavily.com/extract", "Bearer k"))
        self.assertEqual(seen["body"], {"urls": [GATE], "format": "text"})
        self.assertIn("GATE is an entrance exam.\n\nIt is held in February.", result.note)
        self.assertIn('You read the page "GATE"', result.note)
        self.assertIn("never instructions", result.note)
        self.assertEqual((result.trace["read"], result.trace["focused"]), (True, False))

    async def test_about_asks_for_the_parts_on_that_topic(self) -> None:
        bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return _page("Third year students can apply.")(request)

        with patch.dict(os.environ, ON), patch("agent.tools.read_page.httpx.AsyncClient", _client(handler)):
            [result] = await run_calls([ToolCall("read_page", {"url": GATE, "about": " who can   apply "})], CONTEXT)

        self.assertEqual(bodies[0], {"urls": [GATE], "format": "text", "query": "who can apply", "chunks_per_source": 5})
        self.assertIn('the parts of it about "who can apply"', result.note)

    async def test_a_long_page_is_cut_and_says_so(self) -> None:
        with patch.dict(os.environ, ON), patch("agent.tools.read_page.httpx.AsyncClient", _client(_page("word " * 5000))):
            [result] = await run_calls([ToolCall("read_page", {"url": GATE})], CONTEXT)
        self.assertIn(f"cut at {PAGE_CHARS} characters", result.note)
        self.assertLess(len(result.note), PAGE_CHARS + 1200)

    async def test_a_page_that_cannot_be_opened_is_said_plainly(self) -> None:
        failed = lambda request: httpx.Response(200, json={"results": [], "failed_results": [{"url": GATE, "error": "Failed to fetch url"}]})
        with patch.dict(os.environ, ON), patch("agent.tools.read_page.httpx.AsyncClient", _client(failed)):
            [result] = await run_calls([ToolCall("read_page", {"url": GATE})], CONTEXT)
        self.assertIn("could not be opened", result.note)
        self.assertIn("Do not guess", result.note)

    async def test_a_private_address_is_never_sent(self) -> None:
        sent = AsyncMock()
        with patch.dict(os.environ, ON), patch("agent.tools.read_page.read_web_page", sent):
            [result] = await run_calls([ToolCall("read_page", {"url": "http://localhost:8000/admin"})], CONTEXT)
        sent.assert_not_awaited()
        self.assertEqual(result.trace["error"], "not_public")

    async def test_a_link_naming_a_private_person_is_read_only_when_the_user_pasted_it(self) -> None:
        link = "https://www.linkedin.com/in/riya-shah-123"
        sent = AsyncMock(return_value={"title": "Riya", "text": "Profile"})
        with patch.dict(os.environ, ON), patch("agent.tools.read_page.read_web_page", sent), patch("agent.tools.privacy.private_names", return_value={"riya", "shah"}):
            [made_up] = await run_calls([ToolCall("read_page", {"url": link})], ToolContext("u1", user_text="uski profile dekho"))
            [pasted] = await run_calls([ToolCall("read_page", {"url": link})], ToolContext("u1", user_text=f"ye meri dost ki profile hai {link}"))

        self.assertEqual(made_up.trace["blocked"], "private_name")
        self.assertTrue(pasted.trace["read"])
        sent.assert_awaited_once()


class PastedLinkStepTest(unittest.IsolatedAsyncioTestCase):
    def job(self, text: str) -> ReplyJob:
        return ReplyJob([{"role": "user", "content": text}], {}, AsyncMock(), user_id="u1", conversation_id="c1", user_text=text)

    async def test_a_pasted_link_is_read_before_the_reply_is_written(self) -> None:
        calls_seen = []

        async def read(calls, context):
            calls_seen.extend((call.name, call.arguments, context.user_text) for call in calls)
            return [ToolResult("You read the page. GATE is an exam.", {"read": True, "chars": 20}) for _ in calls]

        text = f"ye padh ke bata kya likha hai {GATE}"
        with patch.dict(os.environ, ON), patch("agent.tools.loop.run_calls", read):
            after, info = await read_pasted_links(self.job(text))

        self.assertEqual(calls_seen, [("read_page", {"url": GATE}, text)])
        self.assertEqual([message["role"] for message in after.reply_messages], ["user", "assistant", "tool"])
        self.assertTrue(after.reply_messages[2]["tool_call_id"].startswith("link_"))
        self.assertEqual(info["links"], 1)
        self.assertNotIn("wikipedia", json.dumps(info))  # no address in the trace

    async def test_no_link_or_switched_off_leaves_the_turn_alone(self) -> None:
        reader = AsyncMock()
        with patch("agent.tools.loop.run_calls", reader):
            with patch.dict(os.environ, ON):
                before = self.job("gate ke baare me batao")
                self.assertEqual(await read_pasted_links(before), (before, None))
            with patch.dict(os.environ, {**ON, "AGENT_READ_PASTED_LINKS": "false"}):
                self.assertEqual((await read_pasted_links(self.job(GATE)))[1], None)
            with patch.dict(os.environ, {**ON, "TAVILY_API_KEY": ""}):
                self.assertEqual((await read_pasted_links(self.job(GATE)))[1], None)
        reader.assert_not_awaited()

    async def test_a_failure_never_stops_the_reply(self) -> None:
        before = self.job(f"dekho {GATE}")
        with patch.dict(os.environ, ON), patch("agent.tools.loop.run_calls", AsyncMock(side_effect=RuntimeError("down"))):
            after, info = await read_pasted_links(before)
        self.assertIs(after, before)
        self.assertEqual(info["error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
