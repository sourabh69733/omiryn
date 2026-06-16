#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Assign existing Omiryn rows without user_id to a Supabase user."
    )
    parser.add_argument("--user-id", default=None, help="Supabase auth user UUID.")
    parser.add_argument("--email", default=None, help="Optional email label for operator clarity.")
    parser.add_argument("--dry-run", action="store_true", help="Count rows without updating them.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Also reassign rows that already have a user_id. Use carefully.",
    )
    args = parser.parse_args()
    if not args.user_id and not args.email:
        raise SystemExit("Pass --user-id, or pass --email with SUPABASE_SERVICE_ROLE_KEY set.")

    import sys

    src_path = str(PROJECT_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from sqlalchemy import func, select
    from storage import (
        ENGINE,
        agent_conversations,
        agent_usage_events,
        conversation_context_sources,
        draft_profiles,
        init_db,
    )

    init_db()

    tables = (
        draft_profiles,
        agent_conversations,
        agent_usage_events,
        conversation_context_sources,
    )
    user_id = args.user_id or _lookup_supabase_user_id(args.email)
    print(f"Target user_id: {user_id}")
    if args.email:
        print(f"Email label: {args.email}")

    total = 0
    with ENGINE.begin() as connection:
        for table in tables:
            condition = table.c.id.is_not(None) if args.overwrite else table.c.user_id.is_(None)
            count = connection.execute(
                select(func.count()).select_from(table).where(condition)
            ).scalar_one()
            print(f"{table.name}: {count} row(s)")
            total += count

            if not args.dry_run and count:
                connection.execute(table.update().where(condition).values(user_id=user_id))

    action = "Would assign" if args.dry_run else "Assigned"
    print(f"{action} {total} row(s).")


def _lookup_supabase_user_id(email: str | None) -> str:
    if not email:
        raise SystemExit("Email is required when --user-id is not provided.")

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        raise SystemExit(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to look up a user by email."
        )

    import httpx

    page = 1
    while True:
        response = httpx.get(
            f"{supabase_url}/auth/v1/admin/users",
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
            },
            params={"page": page, "per_page": 1000},
            timeout=20,
        )
        response.raise_for_status()
        users = response.json().get("users", [])
        for user in users:
            if user.get("email", "").lower() == email.lower():
                return user["id"]
        if len(users) < 1000:
            break
        page += 1

    raise SystemExit(f"No Supabase auth user found for email: {email}")


if __name__ == "__main__":
    main()
