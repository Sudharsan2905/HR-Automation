from fastapi import APIRouter, Depends

from app.components.auth.dependencies import require_role
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.hiring import service

router = APIRouter(prefix="/hiring", tags=["Hiring"])
_admin = require_role(Role.INTERVIEWER)  # the super admin passes this check


@router.get("/flows")
async def list_flows(user: User = Depends(_admin)):
    """JDs with their hiring progress."""
    return await service.list_flows(user)


@router.get("/jds/{jd_id}/flow")
async def get_flow(jd_id: str, _user: User = Depends(_admin)):
    """Everything the single hiring page needs for one JD."""
    return await service.get_flow(jd_id)


@router.post("/jds/{jd_id}/level1/start")
async def start_level1(jd_id: str, _user: User = Depends(_admin)):
    """Start or retry Level 1 for the selected profiles."""
    return await service.start_level1(jd_id)


@router.post("/candidates/{hc_id}/level1/resend")
async def resend_level1(hc_id: str, _user: User = Depends(_admin)):
    """Resend the Level 1 invite (with a fresh key)."""
    return await service.resend_level1(hc_id)


@router.post("/candidates/{hc_id}/promote")
async def promote(hc_id: str, _user: User = Depends(_admin)):
    """Admin override: schedule Level 2 regardless of the Level 1 score."""
    return await service.promote_manually(hc_id)


@router.post("/candidates/{hc_id}/level2/resend-key")
async def resend_level2_key(hc_id: str, _user: User = Depends(_admin)):
    """Issue and email a new Level 2 access key."""
    return await service.resend_level2_key(hc_id)


@router.post("/jds/{jd_id}/level1/recheck")
async def recheck_level1(jd_id: str, _user: User = Depends(_admin)):
    """Process Level 1 exams that finished scoring but were not finalized."""
    return await service.recheck_level1(jd_id)
