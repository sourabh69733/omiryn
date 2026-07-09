from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from admin.routes import ADMIN_STATIC_DIR, router as admin_router
from security.auth import current_user
from storage import init_db

from .config import (
    APP_SHELL_HEADERS,
    PROFILE_PHOTO_GCS_BUCKET,
    PROFILE_PHOTO_GCS_PREFIX,
    PROFILE_PHOTO_GCS_PUBLIC_BASE_URL,
    PROFILE_UPLOAD_DIR,
    STATIC_DIR,
)
from .helpers import _agent_user_context, _smart_reply_context_sources
from .routes import run_agent_turn
from .routes import router as api_router

app = FastAPI(
    title="Omiryn API",
    version="0.1.0",
    description="AI-assisted matchmaking platform API.",
)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, object]):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
PROFILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/profile_photos",
    NoCacheStaticFiles(directory=PROFILE_UPLOAD_DIR),
    name="profile-photos",
)
app.mount(
    "/admin/static",
    NoCacheStaticFiles(directory=ADMIN_STATIC_DIR),
    name="admin-static",
)
app.include_router(admin_router)
app.include_router(api_router)


@app.on_event("startup")
def startup() -> None:
    init_db()


__all__ = [
    "APP_SHELL_HEADERS",
    "NoCacheStaticFiles",
    "PROFILE_PHOTO_GCS_BUCKET",
    "PROFILE_PHOTO_GCS_PREFIX",
    "PROFILE_PHOTO_GCS_PUBLIC_BASE_URL",
    "PROFILE_UPLOAD_DIR",
    "STATIC_DIR",
    "_agent_user_context",
    "_smart_reply_context_sources",
    "app",
    "current_user",
    "run_agent_turn",
    "startup",
]
