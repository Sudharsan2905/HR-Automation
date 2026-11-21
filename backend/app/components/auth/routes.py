from fastapi import APIRouter, Depends, Query

from app.components.auth import service
from app.components.auth.dependencies import require_role
from app.components.auth.models import User
from app.components.auth.schemas import (
    CandidateLoginRequest,
    CandidateLinkRequest,
    LoginRequest,
)
from app.components.common.schemas import Role

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login")
async def login(req: LoginRequest):
    """Admin login (single super admin from env)."""
    return await service.login(req)


@router.post("/candidate/login")
async def candidate_login(req: CandidateLoginRequest):
    """Candidate login with the Level 1 access key."""
    return await service.login_candidate(req)


@router.post("/candidates/link")
async def link_candidate(
    req: CandidateLinkRequest,
    user: User = Depends(require_role(Role.INTERVIEWER)),
):
    """Add a candidate to the list."""
    return await service.link_candidate(req, str(user.id))


@router.get("/candidates")
async def list_candidates(user: User = Depends(require_role(Role.INTERVIEWER))):
    """List candidates linked by the current interviewer."""
    candidates = await User.find(
        User.role == Role.CANDIDATE, User.created_by == str(user.id)
    ).to_list()
    return [
        {"id": str(c.id), "email": c.email, "full_name": c.full_name}
        for c in candidates
    ]


@router.delete("/candidate/{candidate_id}")
async def delete_candidate(
    candidate_id: str,
    user: User = Depends(require_role(Role.INTERVIEWER)),
):
    """Delete a candidate."""
    return await service.delete_candidate(candidate_id, str(user.id))
