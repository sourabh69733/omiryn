from __future__ import annotations

import os


DEFAULT_CORS_ORIGINS = (
    "https://omiryn.com",
    "https://www.omiryn.com",
    "https://app.omiryn.com",
)


def configured_cors_origins() -> tuple[str, ...]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    values = configured.split(",") if configured else DEFAULT_CORS_ORIGINS
    return tuple(origin.strip().rstrip("/") for origin in values if origin.strip())
