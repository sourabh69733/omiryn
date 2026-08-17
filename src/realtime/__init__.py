"""Provides transport-neutral realtime events and connection delivery primitives."""

from .contracts import RealtimeEvent, conversation_event, user_event
from .hub import realtime_hub
from .tickets import RealtimeTicketError, issue_realtime_ticket, verify_realtime_ticket

__all__ = [
    "RealtimeEvent",
    "RealtimeTicketError",
    "conversation_event",
    "issue_realtime_ticket",
    "realtime_hub",
    "user_event",
    "verify_realtime_ticket",
]
