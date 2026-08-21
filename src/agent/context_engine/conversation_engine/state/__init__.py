"""Defines and validates persistent conversation progress without changing reply behaviour."""

from .models import ConversationState, ConversationThread
from .context import (
    background_thread_candidates,
    CONVERSATION_THREAD_SOURCE_TYPE,
    conversation_state_shadow_enabled,
    conversation_state_v2_enabled,
    conversation_thread_context_sources,
)
from .service import (
    ConversationStateConflictError,
    create_thread,
    get_state,
    get_thread,
    list_threads,
    save_state,
    update_thread,
)
from .shadow import evaluate_conversation_update_shadow, evaluate_thread_operation_shadow
from .validation import ConversationStateValidationError

__all__ = [
    "ConversationState",
    "ConversationStateConflictError",
    "ConversationStateValidationError",
    "ConversationThread",
    "CONVERSATION_THREAD_SOURCE_TYPE",
    "background_thread_candidates",
    "conversation_state_shadow_enabled",
    "conversation_state_v2_enabled",
    "conversation_thread_context_sources",
    "create_thread",
    "evaluate_conversation_update_shadow",
    "evaluate_thread_operation_shadow",
    "get_state",
    "get_thread",
    "list_threads",
    "save_state",
    "update_thread",
]
