from __future__ import annotations

from fastapi import APIRouter

from . import context, conversations, core, demo, drafts, pages, profile, usage
from .conversations import run_agent_turn

router = APIRouter()
router.include_router(core.router)
router.include_router(profile.router)
router.include_router(usage.router)
router.include_router(context.router)
router.include_router(pages.router)
router.include_router(conversations.router)
router.include_router(drafts.router)
router.include_router(demo.router)

__all__ = ["router", "run_agent_turn"]
