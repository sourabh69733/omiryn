from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from admin.auth import require_admin_user
from admin.service import admin_overview, admin_user_detail
from auth import CurrentUser

ADMIN_STATIC_DIR = Path(__file__).parent / "static"
ADMIN_SHELL_HEADERS = {"Cache-Control": "no-store"}

router = APIRouter()


@router.get("/admin")
@router.get("/admin/users")
@router.get("/admin/usage")
async def admin_shell(_: CurrentUser = Depends(require_admin_user)) -> FileResponse:
    return FileResponse(ADMIN_STATIC_DIR / "index.html", headers=ADMIN_SHELL_HEADERS)


@router.get("/api/admin/overview")
async def admin_overview_endpoint(
    limit: int = 30,
    _: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    return admin_overview(limit=limit)


@router.get("/api/admin/users")
async def admin_users_endpoint(
    limit: int = 100,
    _: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    overview = admin_overview(limit=limit)
    return {"users": overview["users"]}


@router.get("/api/admin/users/{user_id}")
async def admin_user_detail_endpoint(
    user_id: str,
    limit: int = 100,
    _: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    detail = admin_user_detail(user_id, limit=limit)
    if not detail:
        raise HTTPException(status_code=404, detail="Admin user not found.")
    return detail


@router.get("/api/admin/conversations")
async def admin_conversations_endpoint(
    limit: int = 100,
    _: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    overview = admin_overview(limit=limit)
    return {"conversations": overview["recent_conversations"]}


@router.get("/api/admin/drafts")
async def admin_drafts_endpoint(
    limit: int = 100,
    _: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    overview = admin_overview(limit=limit)
    return {"drafts": overview["recent_drafts"]}


@router.get("/api/admin/usage")
async def admin_usage_endpoint(
    limit: int = 100,
    _: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    overview = admin_overview(limit=limit)
    return {
        "summary": overview["summary"]["usage"],
        "events": overview["recent_usage_events"],
        "limits": overview["limits"],
    }
