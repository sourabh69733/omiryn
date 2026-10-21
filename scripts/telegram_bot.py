#!/usr/bin/env python3
"""Set up the Omiryn Telegram bot.

  set-webhook --url https://<api>/api/channels/telegram/webhook   point Telegram at the API
  info                                                              show the current webhook
  delete-webhook                                                    stop webhook delivery
  poll [--api http://127.0.0.1:8001]                                local testing, no public URL

poll asks Telegram for new messages and hands each one to the local API's webhook, the same
way Telegram would. Telegram only allows it while no webhook is set, so it removes the webhook
first. Reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from .env; never prints them.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

_API_BASE = "https://api.telegram.org"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    webhook = commands.add_parser("set-webhook")
    webhook.add_argument("--url", required=True)
    commands.add_parser("info")
    commands.add_parser("delete-webhook")
    poll = commands.add_parser("poll")
    poll.add_argument("--api", default=f"http://127.0.0.1:{os.getenv('APP_PORT', '8001')}")
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not token or not secret:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in .env first.")
        return 1

    if args.command == "set-webhook":
        result = _bot(token, "setWebhook", url=args.url, secret_token=secret, allowed_updates=["message"])
        print("Webhook set." if result.get("ok") else f"Failed: {result.get('description')}")
    elif args.command == "info":
        info = _bot(token, "getWebhookInfo").get("result") or {}
        print(f"url: {info.get('url') or '(none)'}")
        print(f"pending updates: {info.get('pending_update_count', 0)}")
        if info.get("last_error_message"):
            print(f"last error: {info['last_error_message']}")
    elif args.command == "delete-webhook":
        result = _bot(token, "deleteWebhook")
        print("Webhook removed." if result.get("ok") else f"Failed: {result.get('description')}")
    else:
        return _poll(token, secret, args.api.rstrip("/"))
    return 0


def _poll(token: str, secret: str, api: str) -> int:
    _bot(token, "deleteWebhook")
    print(f"Polling Telegram and forwarding to {api}. Ctrl+C to stop.")
    # Forwarded side by side, like Telegram's webhook: the API holds the first message of a
    # burst open while it waits for the rest, so waiting here would stop the rest arriving.
    workers = ThreadPoolExecutor(max_workers=8)
    offset = None
    while True:
        try:
            updates = _bot(token, "getUpdates", timeout=30, offset=offset, allowed_updates=["message"])
        except httpx.HTTPError as error:
            print(f"Telegram unreachable ({type(error).__name__}); retrying.")
            time.sleep(3)
            continue
        for update in updates.get("result") or []:
            offset = update["update_id"] + 1
            workers.submit(_forward, api, secret, update)


def _forward(api: str, secret: str, update: dict) -> None:
    try:
        response = httpx.post(
            f"{api}/api/channels/telegram/webhook",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            timeout=120,
        )
        print(f"update {update['update_id']}: {response.status_code}")
    except httpx.HTTPError as error:
        print(f"update {update['update_id']}: API unreachable ({type(error).__name__})")


def _bot(token: str, method: str, **payload: object) -> dict:
    body = {key: value for key, value in payload.items() if value is not None}
    response = httpx.post(f"{_API_BASE}/bot{token}/{method}", json=body, timeout=40)
    return response.json()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
