"""Provides transport-neutral realtime events and connection delivery primitives."""

from .contracts import RealtimeEvent, conversation_event, user_event
from .fanout import RealtimeFanout
from .hub import realtime_hub

realtime_fanout = RealtimeFanout(realtime_hub)
realtime_hub.attach_fanout(realtime_fanout)
from .tickets import RealtimeTicketError, issue_realtime_ticket, verify_realtime_ticket

__all__ = [
    "RealtimeEvent",
    "RealtimeTicketError",
    "conversation_event",
    "issue_realtime_ticket",
    "realtime_fanout",
    "realtime_hub",
    "user_event",
    "verify_realtime_ticket",
]
