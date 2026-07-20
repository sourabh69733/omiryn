from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from storage import save_public_event, save_public_lead

from ..models import PublicEventCreate, PublicLeadCreate

router = APIRouter()


@router.post("/api/public/events", status_code=201)
async def create_public_event(payload: PublicEventCreate, request: Request) -> dict[str, object]:
    metadata = _with_request_metadata(payload.metadata, request)
    event = save_public_event({**payload.model_dump(), "metadata": metadata})
    return {"event": event}


@router.post("/api/public/leads", status_code=201)
async def create_public_lead(payload: PublicLeadCreate, request: Request) -> dict[str, object]:
    if len(payload.contact.strip()) < 3:
        raise HTTPException(status_code=422, detail="Contact is required.")
    metadata = _with_request_metadata(payload.metadata, request)
    lead = save_public_lead({**payload.model_dump(), "metadata": metadata})
    return {"lead": lead}


def _with_request_metadata(metadata: dict[str, object], request: Request) -> dict[str, object]:
    client_host = request.client.host if request.client else None
    return {
        **metadata,
        "user_agent": request.headers.get("user-agent"),
        "client_host": client_host,
    }
