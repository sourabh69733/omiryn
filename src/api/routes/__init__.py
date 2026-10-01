from __future__ import annotations

from fastapi import APIRouter

from . import (
    agent_settings,
    context,
    conversations,
    core,
    demo,
    drafts,
    memories,
    profile,
    public,
    realtime,
    usage,
    vibe,
)
from .conversations import run_agent_turn

router = APIRouter()
router.include_router(core.router)
router.include_router(profile.router)
router.include_router(memories.router)
router.include_router(public.router)
router.include_router(usage.router)
router.include_router(context.router)
router.include_router(conversations.router)
router.include_router(agent_settings.router)
router.include_router(realtime.router)
router.include_router(drafts.router)
router.include_router(demo.router)
router.include_router(vibe.router)

__all__ = ["router", "run_agent_turn"]
