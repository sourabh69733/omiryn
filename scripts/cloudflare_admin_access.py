"""Put Cloudflare Access in front of the admin site, so only listed emails can even load the page.

Creates or updates, by name and domain, so running it again is safe:
  1. the One-time PIN login method (Cloudflare emails a code), when no PIN method exists yet;
  2. a reusable Allow policy, "Omiryn admins", listing the admin emails;
  3. a self-hosted Access application for the admin domain that uses that policy.

The API behind admin.omiryn.com keeps its own admin check; this is a second lock in front of the page.

Needs two environment variables, set in your own shell (never in a file in the repo):
  CLOUDFLARE_API_TOKEN   token with "Access: Apps and Policies Write" and
                         "Access: Organizations, Identity Providers, and Groups Write"
  CLOUDFLARE_ACCOUNT_ID  from the Cloudflare dashboard

Dry run by default; --apply makes the changes:
  python3 scripts/cloudflare_admin_access.py --email you@example.com
  python3 scripts/cloudflare_admin_access.py --email you@example.com --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Protocol

API = "https://api.cloudflare.com/client/v4"
POLICY_NAME = "Omiryn admins"
APP_NAME = "Omiryn Admin"
SESSION_DURATION = "24h"


class Client(Protocol):
    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any: ...


class CloudflareClient:
    def __init__(self, token: str, account_id: str) -> None:
        self._token = token
        self._base = f"{API}/accounts/{account_id}"

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            self._base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            payload = json.loads(error.read() or b"{}")
        if not payload.get("success"):
            messages = "; ".join(item.get("message", "") for item in payload.get("errors", [])) or "unknown error"
            raise SystemExit(f"Cloudflare refused {method} {path}: {messages}")
        return payload.get("result")


def policy_body(emails: list[str]) -> dict[str, Any]:
    return {
        "name": POLICY_NAME,
        "decision": "allow",
        "include": [{"email": {"email": email}} for email in emails],
        "session_duration": SESSION_DURATION,
    }


def app_body(domain: str, policy_id: str) -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "domain": domain,
        "type": "self_hosted",
        "session_duration": SESSION_DURATION,
        "policies": [{"id": policy_id, "precedence": 1}],
    }


def plan_and_apply(client: Client, domain: str, emails: list[str], *, apply: bool, log=print) -> None:
    """Work out what is missing or different, say it, and change it only when `apply` is set."""
    prefix = "" if apply else "[dry run] "

    providers = client.call("GET", "/access/identity_providers") or []
    if any(provider.get("type") == "onetimepin" for provider in providers):
        log("Login method: One-time PIN already on.")
    else:
        log(f"{prefix}Login method: turning on One-time PIN (a code by email).")
        if apply:
            client.call("POST", "/access/identity_providers", {"name": "One-time PIN", "type": "onetimepin", "config": {}})

    policies = client.call("GET", "/access/policies") or []
    policy = next((item for item in policies if item.get("name") == POLICY_NAME), None)
    body = policy_body(emails)
    if policy is None:
        log(f"{prefix}Policy: creating '{POLICY_NAME}' for {', '.join(emails)}.")
        policy_id = client.call("POST", "/access/policies", body)["id"] if apply else "<new policy>"
    else:
        policy_id = policy["id"]
        log(f"{prefix}Policy: setting '{POLICY_NAME}' to {', '.join(emails)}.")
        if apply:
            client.call("PUT", f"/access/policies/{policy_id}", body)

    apps = client.call("GET", "/access/apps") or []
    app = next((item for item in apps if item.get("domain") == domain), None)
    body = app_body(domain, policy_id)
    if app is None:
        log(f"{prefix}Application: protecting {domain}.")
        if apply:
            client.call("POST", "/access/apps", body)
    else:
        log(f"{prefix}Application: {domain} is already protected; making sure it uses '{POLICY_NAME}'.")
        if apply:
            client.call("PUT", f"/access/apps/{app['id']}", body)

    log("Done. Open the admin site in a private window to check." if apply else "Nothing changed. Run again with --apply.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", action="append", required=True, help="An admin's email; repeat for more.")
    parser.add_argument("--domain", default="admin.omiryn.com")
    parser.add_argument("--apply", action="store_true", help="Make the changes (default: only show them).")
    args = parser.parse_args(argv)

    token = os.getenv("CLOUDFLARE_API_TOKEN")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account_id:
        sys.exit("Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in this shell first (see the top of this file).")
    emails = sorted({email.strip().lower() for email in args.email if email.strip()})
    plan_and_apply(CloudflareClient(token, account_id), args.domain, emails, apply=args.apply)


if __name__ == "__main__":
    main()
