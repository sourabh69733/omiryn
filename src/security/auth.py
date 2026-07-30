from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from inspect import isawaitable, signature
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


class ProductionSecurityConfigError(RuntimeError):
    pass


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
    override = request.app.dependency_overrides.get(current_user)
    if override:
        parameters = signature(override).parameters
        result = override(request) if parameters else override()
        user = await result if isawaitable(result) else result
        if user:
            return user

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


def validate_production_security_config() -> None:
    if not production_runtime_enabled():
        return

    failures = []
    database_url = _env("DATABASE_URL")
    if _env("AUTH_REQUIRED").lower() != "true":
        failures.append("AUTH_REQUIRED must be true")
    if _env("AUTH_PROVIDER").lower() != "supabase":
        failures.append("AUTH_PROVIDER must be supabase")
    if not _env("SUPABASE_URL"):
        failures.append("SUPABASE_URL is required")
    if not _env("SUPABASE_ANON_KEY"):
        failures.append("SUPABASE_ANON_KEY is required")
    if not database_url:
        failures.append("DATABASE_URL is required")
    elif database_url.lower().startswith("sqlite"):
        failures.append("DATABASE_URL must use Postgres, not SQLite")
    if not _valid_encryption_master_key():
        failures.append("ENCRYPTION_MASTER_KEY must be a base64 encoded 32-byte key")
    if not _valid_secret_key():
        failures.append("SECRET_KEY must be set to a non-default value with at least 32 characters")
    if _env("ADMIN_ALLOW_UNAUTHENTICATED_DEV").lower() == "true":
        failures.append("ADMIN_ALLOW_UNAUTHENTICATED_DEV must be false")
    if not (_configured_values("ADMIN_EMAILS") or _configured_values("ADMIN_USER_IDS")):
        failures.append("ADMIN_EMAILS or ADMIN_USER_IDS must configure at least one admin")
    if not _env("PROFILE_PHOTO_GCS_BUCKET"):
        failures.append("PROFILE_PHOTO_GCS_BUCKET is required for durable production photo storage")
    if not _valid_profile_photo_max_mb():
        failures.append("PROFILE_PHOTO_MAX_MB must be greater than 0 and no more than 10")

    if failures:
        raise ProductionSecurityConfigError(
            "Unsafe production security configuration: " + "; ".join(failures)
        )


def production_runtime_enabled() -> bool:
    runtime = (_env("APP_ENV") or _env("ENVIRONMENT") or _env("ENV")).lower()
    if runtime in {"production", "prod"}:
        return True
    if runtime in {"development", "dev", "local", "test", "testing"}:
        return False
    return bool(_env("K_SERVICE") or _env("K_REVISION") or _env("K_CONFIGURATION")) or (
        _env("VERCEL_ENV").lower() == "production"
    )


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


def _configured_values(name: str) -> set[str]:
    return {value.strip().lower() for value in _env(name).split(",") if value.strip()}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _valid_encryption_master_key() -> bool:
    raw = _env("ENCRYPTION_MASTER_KEY")
    if not raw:
        return False
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError:
        return False
    return len(key) == 32


def _valid_secret_key() -> bool:
    value = _env("SECRET_KEY")
    if not value or value == "change-me-in-local-env":
        return False
    return len(value) >= 32


def _valid_profile_photo_max_mb() -> bool:
    raw = _env("PROFILE_PHOTO_MAX_MB") or "10"
    try:
        value = float(raw)
    except ValueError:
        return False
    return 0 < value <= 10


def _metadata_display_name(metadata: dict[str, Any]) -> str | None:
    for key in ("full_name", "name", "display_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata_avatar_url(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("avatar_url") or metadata.get("picture")
    return value.strip() if isinstance(value, str) and value.strip() else None
