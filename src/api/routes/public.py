from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import APIRouter, HTTPException, Request

from storage import save_public_event, save_public_lead

from ..models import PublicEventCreate, PublicLeadCreate

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RATE_LIMIT_WINDOW_SECONDS = 60
_EVENT_LIMIT_PER_WINDOW = 90
_LEAD_LIMIT_PER_WINDOW = 5
_public_rate_buckets: dict[tuple[str, str], Deque[float]] = defaultdict(deque)


@router.post("/api/public/events", status_code=201)
async def create_public_event(payload: PublicEventCreate, request: Request) -> dict[str, object]:
    _check_public_rate_limit(request, "events", _EVENT_LIMIT_PER_WINDOW)
    metadata = _with_request_metadata(payload.metadata, request)
    event = save_public_event({**payload.model_dump(), "metadata": metadata})
    return {"event": event}


@router.post("/api/public/leads", status_code=201)
async def create_public_lead(payload: PublicLeadCreate, request: Request) -> dict[str, object]:
    _check_public_rate_limit(request, "leads", _LEAD_LIMIT_PER_WINDOW)
    contact = payload.contact.strip().lower()
    message = payload.message.strip()
    if len(contact) < 3:
        raise HTTPException(status_code=422, detail="Contact is required.")
    if not _EMAIL_RE.match(contact):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if len(message) < 10:
        raise HTTPException(status_code=422, detail="Message must be at least 10 characters.")
    metadata = _with_request_metadata(payload.metadata, request)
    lead = save_public_lead({**payload.model_dump(), "contact": contact, "message": message, "metadata": metadata})
    return {"lead": lead}


def _with_request_metadata(metadata: dict[str, object], request: Request) -> dict[str, object]:
    client_host = request.client.host if request.client else None
    return {
        **metadata,
        "user_agent": request.headers.get("user-agent"),
        "client_host": client_host,
    }


def _check_public_rate_limit(request: Request, scope: str, limit: int) -> None:
    client_host = request.client.host if request.client else "unknown"
    key = (scope, client_host)
    now = time.monotonic()
    bucket = _public_rate_buckets[key]
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again soon.")
    bucket.append(now)


def _reset_public_rate_limits() -> None:
    _public_rate_buckets.clear()
