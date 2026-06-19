from __future__ import annotations

import os

from fastapi import Depends, HTTPException

from auth import CurrentUser, auth_required, current_user


def configured_admin_emails() -> set[str]:
    return _configured_values("ADMIN_EMAILS")


def configured_admin_user_ids() -> set[str]:
    return _configured_values("ADMIN_USER_IDS")


async def require_admin_user(user: CurrentUser | None = Depends(current_user)) -> CurrentUser:
    emails = configured_admin_emails()
    user_ids = configured_admin_user_ids()

    if not emails and not user_ids and _allow_dev_admin_without_auth():
        return user or CurrentUser(id="local-admin", email=None)

    if not user:
        raise HTTPException(status_code=401, detail="Admin sign-in required.")

    if user.id in user_ids:
        return user
    if user.email and user.email.lower() in emails:
        return user

    raise HTTPException(status_code=403, detail="Admin access is not enabled for this account.")


def _configured_values(name: str) -> set[str]:
    return {
        value.strip().lower()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    }


def _allow_dev_admin_without_auth() -> bool:
    configured = os.getenv("ADMIN_ALLOW_UNAUTHENTICATED_DEV", "")
    if configured:
        return configured.lower() == "true"
    return not auth_required()
