from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from ..config import APP_SHELL_HEADERS, STATIC_DIR
from ..helpers import _get_existing_draft

router = APIRouter()


@router.get("/")
def root(request: Request) -> FileResponse:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host.startswith("app."):
        return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)
    return FileResponse(STATIC_DIR / "landing.html", headers=APP_SHELL_HEADERS)


@router.get("/app")
def app_shell() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/drafts/{draft_id}")
def draft_review_page(draft_id: str) -> FileResponse:
    _get_existing_draft(draft_id)
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/matches")
def matches_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/style")
def style_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)


@router.get("/usage")
def usage_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=APP_SHELL_HEADERS)

