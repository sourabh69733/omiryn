from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from storage import reserve_user_app_event


@dataclass(frozen=True)
class UserActionLimit:
    action: str
    event_name: str
    monthly_env: str
    monthly_default: int
    label: str


CHAT_MESSAGE_LIMIT = UserActionLimit(
    action="chat_message",
    event_name="quota.chat_message",
    monthly_env="USER_CHAT_MONTHLY_LIMIT",
    monthly_default=300,
    label="chat messages",
)
CONTEXT_IMPORT_LIMIT = UserActionLimit(
    action="context_import",
    event_name="quota.context_import",
    monthly_env="USER_CONTEXT_IMPORT_MONTHLY_LIMIT",
    monthly_default=10,
    label="memory imports",
)
WHATSAPP_IMPORT_LIMIT = UserActionLimit(
    action="whatsapp_import",
    event_name="quota.whatsapp_import",
    monthly_env="USER_WHATSAPP_IMPORT_MONTHLY_LIMIT",
    monthly_default=3,
    label="WhatsApp imports",
)

# The short abuse-control window is fixed; product-level monthly quotas remain configurable.
_BURST_WINDOW = timedelta(seconds=60)


def enforce_user_action_limit(user_id: str, limit: UserActionLimit) -> None:
    now = datetime.now(timezone.utc)
    monthly_limit = _env_int(limit.monthly_env, limit.monthly_default)
    burst_limit = _derived_burst_limit(monthly_limit)
    window_days = _env_int("USER_LIMIT_MONTH_DAYS", 30)
    month_window = timedelta(days=window_days)
    # Storage performs the limit checks and reservation atomically. Reserve before
    # downstream work so simultaneous requests cannot overspend the same quota slot.
    result = reserve_user_app_event(
        user_id,
        limit.event_name,
        {
            "action": limit.action,
            "monthly_limit": monthly_limit,
            "burst_limit": burst_limit,
            "burst_seconds": int(_BURST_WINDOW.total_seconds()),
        },
        monthly_since=now - month_window if monthly_limit > 0 else None,
        monthly_limit=monthly_limit,
        burst_since=now - _BURST_WINDOW if burst_limit else None,
        burst_limit=burst_limit,
    )

    if result["allowed"]:
        return
    if result["reason"] == "monthly":
        retry_after = _retry_after_seconds(result["oldest_created_at"], now, month_window)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly limit reached for {limit.label}. "
                "Please try again when your quota resets."
            ),
            headers=_rate_limit_headers(retry_after),
        )
    retry_after = _retry_after_seconds(result["oldest_created_at"], now, _BURST_WINDOW)
    raise HTTPException(
        status_code=429,
        detail="Too many requests in a short time. Please wait a minute and try again.",
        headers=_rate_limit_headers(retry_after),
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _derived_burst_limit(monthly_limit: int) -> int | None:
    if monthly_limit <= 0:
        return None
    return min(monthly_limit, 10)


def _retry_after_seconds(oldest_created_at: datetime | None, now: datetime, window: timedelta) -> int:
    if oldest_created_at is None:
        return int(window.total_seconds())
    if oldest_created_at.tzinfo is None:
        oldest_created_at = oldest_created_at.replace(tzinfo=timezone.utc)
    reset_at = oldest_created_at + window
    return max(1, int((reset_at - now).total_seconds()) + 1)


def _rate_limit_headers(retry_after_seconds: int) -> dict[str, str]:
    return {
        "Retry-After": str(retry_after_seconds),
        "X-RateLimit-Reset-Seconds": str(retry_after_seconds),
    }
