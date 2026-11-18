"""Aggregates every Level 1 router (mounted under /api in main)."""

from fastapi import APIRouter

from app.components.level1.assessment_router import router as review_router
from app.components.level1.candidate_router import router as exam_router
from app.components.level1.ws_router import ws_router

router = APIRouter()
router.include_router(exam_router)
router.include_router(review_router)
router.include_router(ws_router)
