from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "false").lower() == "true"


async def current_user(request: Request) -> CurrentUser | None:
    token = _bearer_token(request)
    if not token:
        if auth_required():
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        return None

    return await _verify_supabase_token(token)


async def require_user(request: Request) -> CurrentUser:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return await _verify_supabase_token(token)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def _verify_supabase_token(token: str) -> CurrentUser:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    if not supabase_url or not anon_key:
        raise HTTPException(status_code=500, detail="Supabase auth is not configured.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "apikey": anon_key,
                    "Authorization": f"Bearer {token}",
                },
            )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Could not verify sign-in.") from error

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Sign in to continue.")

    payload = response.json()
    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue.")

    metadata = payload.get("user_metadata") or {}
    return CurrentUser(
        id=user_id,
        email=payload.get("email"),
        display_name=_metadata_display_name(metadata),
        avatar_url=_metadata_avatar_url(metadata),
    )


def _metadata_display_name(metadata: dict[str, Any]) -> str | None:
    for key in ("full_name", "name", "display_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata_avatar_url(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("avatar_url") or metadata.get("picture")
    return value.strip() if isinstance(value, str) and value.strip() else None
