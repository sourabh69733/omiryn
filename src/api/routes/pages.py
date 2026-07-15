from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..config import APP_SHELL_HEADERS, FRONTEND_DIST_DIR, LANDING_PAGE_FILE
from ..helpers import _get_existing_draft

router = APIRouter()


@router.get("/")
def root() -> FileResponse:
    return FileResponse(LANDING_PAGE_FILE, headers=APP_SHELL_HEADERS)


@router.get("/app")
def app_shell() -> FileResponse:
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/app-react")
def react_app_preview() -> FileResponse:
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/drafts/{draft_id}")
def draft_review_page(draft_id: str) -> FileResponse:
    _get_existing_draft(draft_id)
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/matches")
def matches_page() -> FileResponse:
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/style")
def style_page() -> FileResponse:
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/usage")
def usage_page() -> FileResponse:
    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers=APP_SHELL_HEADERS)
