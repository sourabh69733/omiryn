from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import require_admin_user
from admin.service import admin_eval_runs, admin_overview, admin_requests, admin_user_detail
from security.auth import CurrentUser
from storage.audit_log import list_audit_events, record_audit_event

router = APIRouter()


@router.get("/api/admin/overview")
async def admin_overview_endpoint(
    limit: int = 30,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_overview", actor_id=admin.id, actor_role="admin")
    return admin_overview(limit=limit)


@router.get("/api/admin/users")
async def admin_users_endpoint(
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_users", actor_id=admin.id, actor_role="admin")
    overview = admin_overview(limit=limit)
    return {"users": overview["users"]}


@router.get("/api/admin/users/{user_id}")
async def admin_user_detail_endpoint(
    user_id: str,
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_user", actor_id=admin.id, actor_role="admin", target_user_id=user_id)
    detail = admin_user_detail(user_id, limit=limit)
    if not detail:
        raise HTTPException(status_code=404, detail="Admin user not found.")
    return detail


@router.get("/api/admin/conversations")
async def admin_conversations_endpoint(
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_conversations", actor_id=admin.id, actor_role="admin")
    overview = admin_overview(limit=limit)
    return {"conversations": overview["recent_conversations"]}


@router.get("/api/admin/drafts")
async def admin_drafts_endpoint(
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_drafts", actor_id=admin.id, actor_role="admin")
    overview = admin_overview(limit=limit)
    return {"drafts": overview["recent_drafts"]}


@router.get("/api/admin/usage")
async def admin_usage_endpoint(
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_usage", actor_id=admin.id, actor_role="admin")
    overview = admin_overview(limit=limit)
    return {
        "summary": overview["summary"]["usage"],
        "events": overview["recent_usage_events"],
        "limits": overview["limits"],
    }


@router.get("/api/admin/requests")
async def admin_requests_endpoint(
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_requests", actor_id=admin.id, actor_role="admin")
    return admin_requests(limit=limit)


@router.get("/api/admin/evals")
async def admin_evals_endpoint(
    limit: int = 50,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_evals", actor_id=admin.id, actor_role="admin")
    return admin_eval_runs(limit=limit)


@router.get("/api/admin/audit")
async def admin_audit_endpoint(
    user_id: str | None = None,
    limit: int = 100,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, object]:
    record_audit_event("admin.view_audit", actor_id=admin.id, actor_role="admin", target_user_id=user_id)
    return {"events": list_audit_events(target_user_id=user_id, limit=limit)}
