"""Defines and validates persistent conversation progress without changing reply behaviour."""

from .models import ConversationState, ConversationThread
from .service import (
    ConversationStateConflictError,
    create_thread,
    get_state,
    get_thread,
    list_threads,
    save_state,
    update_thread,
)
from .validation import ConversationStateValidationError

__all__ = [
    "ConversationState",
    "ConversationStateConflictError",
    "ConversationStateValidationError",
    "ConversationThread",
    "create_thread",
    "get_state",
    "get_thread",
    "list_threads",
    "save_state",
    "update_thread",
]
