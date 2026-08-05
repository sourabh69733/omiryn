from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - keeps tests usable before deps install
    load_dotenv = None

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

try:
    from google.cloud import storage as gcs_storage
except ModuleNotFoundError:  # pragma: no cover - optional outside GCP/photo uploads
    gcs_storage = None

FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
PROFILE_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads" / "profile_photos"
APP_SHELL_HEADERS = {"Cache-Control": "no-store"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


PROFILE_PHOTO_MAX_BYTES = int(_float_env("PROFILE_PHOTO_MAX_MB", 10) * 1024 * 1024)
PROFILE_PHOTO_MAX_COUNT = 4
PROFILE_PHOTO_GCS_BUCKET = os.getenv("PROFILE_PHOTO_GCS_BUCKET", "").strip()
PROFILE_PHOTO_GCS_PREFIX = os.getenv("PROFILE_PHOTO_GCS_PREFIX", "profile_photos").strip("/")
PROFILE_PHOTO_GCS_PUBLIC_BASE_URL = os.getenv("PROFILE_PHOTO_GCS_PUBLIC_BASE_URL", "").strip().rstrip("/")
PROFILE_PHOTO_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
DEFAULT_AGENT_COUNTRY = os.getenv("AGENT_DEFAULT_COUNTRY", "India")
DEFAULT_AGENT_TIMEZONE = os.getenv("AGENT_DEFAULT_TIMEZONE", "Asia/Kolkata")
LLM_CONTEXT_IMPORT_PROMPT = 'LLM_CONTEXT_IMPORT_PROMPT = """I am using Omiryn to build a private personal profile about myself.\n\nPlease create a concise, privacy-safe self-profile about me based only on what you know from our past chats.\nFocus on me as a person, not on my dating life. Include relationship details only if I clearly discussed them before.\n\nReturn sections:\n1. Basic background and life context, only if known\n2. Personality traits and temperament\n3. Core values, priorities, and beliefs\n4. Interests, hobbies, routines, and lifestyle patterns\n5. Communication style and thinking style\n6. Goals, ambitions, and current focus areas\n7. Strengths, recurring challenges, and stress patterns\n8. Preferences, dislikes, boundaries, and sensitivities\n9. Important unknowns Omiryn should ask me\n\nRules:\n- Do not invent facts.\n- Mark uncertain points as uncertain.\n- Do not infer romantic status, past relationships, sexual preferences, attraction patterns, or ideal partner unless explicitly known.\n- Avoid exposing names, phone numbers, addresses, or private third-party details.\n- Keep it under 1000 words.\n"""'
