from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from api.models import AppEventCreate, AppEventName
from api.routes.profile import _APP_EVENT_METADATA_ALLOWLIST


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_LOGGER = PROJECT_ROOT / "frontend" / "src" / "lib" / "appLogger.ts"


def test_frontend_and_backend_app_event_names_match() -> None:
    frontend_source = FRONTEND_LOGGER.read_text(encoding="utf-8")
    event_type = re.search(
        r"type AppEventName\s*=\s*(.*?);",
        frontend_source,
        flags=re.DOTALL,
    )

    assert event_type is not None
    frontend_names = set(re.findall(r'"([a-z0-9_]+)"', event_type.group(1)))
    backend_names = set(get_args(AppEventName))
    assert frontend_names == backend_names


def test_every_learned_signal_event_is_accepted() -> None:
    learned_signal_events = {
        "learned_signal_edited",
        "learned_signal_deleted",
        "learned_signal_confirmed",
        "learned_signal_rejected",
        "learned_signal_feedback_sent",
        "learned_signal_privacy_updated",
        "learned_signal_restored",
    }

    for event_name in learned_signal_events:
        event = AppEventCreate.model_validate(
            {
                "event_name": event_name,
                "page": "style",
                "target_type": "profile_fact",
                "target_id": "fact-a",
            }
        )
        assert event.event_name == event_name


def test_feedback_rating_metadata_is_allowed_end_to_end() -> None:
    frontend_source = FRONTEND_LOGGER.read_text(encoding="utf-8")
    safe_metadata = re.search(
        r"function safeMetadata\(.*?const allowedKeys = new Set\(\[(.*?)\]\);",
        frontend_source,
        flags=re.DOTALL,
    )

    assert safe_metadata is not None
    frontend_keys = set(re.findall(r'"([a-z0-9_]+)"', safe_metadata.group(1)))
    assert "rating" in frontend_keys
    assert "rating" in _APP_EVENT_METADATA_ALLOWLIST
