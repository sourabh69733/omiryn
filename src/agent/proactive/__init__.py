"""Agent-initiated messaging: policy, generation and scheduling."""

from .policy import ProactiveLimits, nudge_block_reason, pick_thread, return_greeting_block_reason
from .service import (
    greet_on_return,
    proactive_messaging_enabled,
    proactive_scheduler,
    run_proactive_pass,
    schedule_return_greeting,
)

__all__ = [
    "ProactiveLimits",
    "greet_on_return",
    "nudge_block_reason",
    "pick_thread",
    "proactive_messaging_enabled",
    "proactive_scheduler",
    "return_greeting_block_reason",
    "run_proactive_pass",
    "schedule_return_greeting",
]
