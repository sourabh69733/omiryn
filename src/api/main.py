from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from admin.routes import ADMIN_STATIC_DIR, router as admin_router
from security.auth import current_user, production_runtime_enabled, validate_production_security_config
from storage import init_db, validate_private_data_ownership

from .config import (
    CORS_ALLOWED_ORIGINS,
    PROFILE_PHOTO_GCS_BUCKET,
    PROFILE_PHOTO_GCS_PREFIX,
    PROFILE_PHOTO_GCS_PUBLIC_BASE_URL,
    PROFILE_UPLOAD_DIR,
)
from .helpers import _agent_user_context, _smart_reply_context_sources
from .routes import run_agent_turn
from .routes import router as api_router

app = FastAPI(
    title="Omiryn API",
    version="0.1.0",
    description="AI-assisted matchmaking platform API.",
)

logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, object]):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


@app.middleware("http")
async def request_monitoring_middleware(request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "api.unhandled_error request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong.", "request_id": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    return response


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
    validate_production_security_config()
    init_db()
    if production_runtime_enabled():
        validate_private_data_ownership()


__all__ = [
    "CORS_ALLOWED_ORIGINS",
    "NoCacheStaticFiles",
    "PROFILE_PHOTO_GCS_BUCKET",
    "PROFILE_PHOTO_GCS_PREFIX",
    "PROFILE_PHOTO_GCS_PUBLIC_BASE_URL",
    "PROFILE_UPLOAD_DIR",
    "_agent_user_context",
    "_smart_reply_context_sources",
    "app",
    "current_user",
    "run_agent_turn",
    "startup",
]
