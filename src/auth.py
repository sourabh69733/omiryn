from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class AuthProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        ...

    async def verify_token(self, token: str) -> CurrentUser:
        ...


class SupabaseAuthProvider:
    name = "supabase"

    def __init__(self) -> None:
        self.supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.anon_key = os.getenv("SUPABASE_ANON_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.supabase_url and self.anon_key)

    async def verify_token(self, token: str) -> CurrentUser:
        if not self.is_configured():
            raise HTTPException(status_code=500, detail="Supabase auth is not configured.")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.supabase_url}/auth/v1/user",
                    headers={
                        "apikey": self.anon_key,
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


class UnconfiguredAuthProvider:
    name = "none"

    def is_configured(self) -> bool:
        return False

    async def verify_token(self, token: str) -> CurrentUser:
        raise HTTPException(status_code=500, detail="Auth provider is not configured.")


def auth_required() -> bool:
    explicit = os.getenv("AUTH_REQUIRED")
    if explicit is not None and explicit.strip():
        return explicit.lower() == "true"
    provider = configured_auth_provider()
    return provider.is_configured()


async def current_user(request: Request) -> CurrentUser | None:
    token = _bearer_token(request)
    if not token:
        if auth_required():
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        return None

    return await configured_auth_provider().verify_token(token)


async def require_user(request: Request) -> CurrentUser:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return await configured_auth_provider().verify_token(token)


def configured_auth_provider() -> AuthProvider:
    provider_name = os.getenv("AUTH_PROVIDER", "").strip().lower()
    if not provider_name:
        provider_name = "supabase" if SupabaseAuthProvider().is_configured() else "none"
    if provider_name == "supabase":
        return SupabaseAuthProvider()
    if provider_name in {"none", "local", "disabled"}:
        return UnconfiguredAuthProvider()
    raise HTTPException(status_code=500, detail=f"Unsupported auth provider: {provider_name}")


def public_auth_config() -> dict[str, object]:
    provider = configured_auth_provider()
    config: dict[str, object] = {
        "auth_provider": provider.name,
        "auth_required": auth_required(),
        "auth_gate_required": provider.is_configured() or auth_required(),
        "providers": {},
    }
    if isinstance(provider, SupabaseAuthProvider):
        supabase_config = {
            "url": provider.supabase_url,
            "anon_key": provider.anon_key,
        }
        config["providers"] = {"supabase": supabase_config}
        # Legacy keys are kept until the browser auth adapter stops reading them.
        config["supabase_url"] = provider.supabase_url
        config["supabase_anon_key"] = provider.anon_key
    return config


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _metadata_display_name(metadata: dict[str, Any]) -> str | None:
    for key in ("full_name", "name", "display_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata_avatar_url(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("avatar_url") or metadata.get("picture")
    return value.strip() if isinstance(value, str) and value.strip() else None
