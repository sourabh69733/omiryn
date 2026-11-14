"""The Cloudflare Access script changes nothing on a dry run and creates or updates by name on --apply."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cloudflare_admin_access.py"
spec = importlib.util.spec_from_file_location("cloudflare_admin_access", SCRIPT)
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class FakeCloudflare:
    def __init__(self, providers=(), policies=(), apps=()) -> None:
        self.state = {"/access/identity_providers": list(providers), "/access/policies": list(policies), "/access/apps": list(apps)}
        self.writes: list[tuple[str, str, dict]] = []

    def call(self, method, path, body=None):
        if method == "GET":
            return self.state[path]
        self.writes.append((method, path, body))
        return {"id": "new-id"}


class AdminAccessScriptTest(unittest.TestCase):
    def run_script(self, fake, apply):
        lines = []
        access.plan_and_apply(fake, "admin.omiryn.com", ["me@example.com"], apply=apply, log=lines.append)
        return lines

    def test_dry_run_only_reads(self) -> None:
        fake = FakeCloudflare()
        lines = self.run_script(fake, apply=False)
        self.assertEqual(fake.writes, [])
        self.assertTrue(all(line.startswith("[dry run]") for line in lines[:3]))

    def test_first_run_creates_pin_policy_and_app(self) -> None:
        fake = FakeCloudflare()
        self.run_script(fake, apply=True)
        self.assertEqual([(method, path) for method, path, _ in fake.writes], [
            ("POST", "/access/identity_providers"),
            ("POST", "/access/policies"),
            ("POST", "/access/apps"),
        ])
        policy = fake.writes[1][2]
        self.assertEqual((policy["decision"], policy["include"]), ("allow", [{"email": {"email": "me@example.com"}}]))
        app = fake.writes[2][2]
        self.assertEqual((app["domain"], app["type"], app["policies"]), ("admin.omiryn.com", "self_hosted", [{"id": "new-id", "precedence": 1}]))

    def test_second_run_updates_in_place(self) -> None:
        fake = FakeCloudflare(
            providers=[{"type": "onetimepin"}],
            policies=[{"id": "p1", "name": access.POLICY_NAME}],
            apps=[{"id": "a1", "domain": "admin.omiryn.com"}],
        )
        self.run_script(fake, apply=True)
        self.assertEqual([(method, path) for method, path, _ in fake.writes], [
            ("PUT", "/access/policies/p1"),
            ("PUT", "/access/apps/a1"),
        ])
        self.assertEqual(fake.writes[1][2]["policies"], [{"id": "p1", "precedence": 1}])


if __name__ == "__main__":
    unittest.main()
