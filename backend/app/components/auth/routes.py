from fastapi import APIRouter, Depends, Query

from app.components.auth import service
from app.components.auth.dependencies import require_role
from app.components.auth.models import User
from app.components.auth.schemas import (
    CandidateLoginRequest,
    CandidateLinkRequest,
    LoginRequest,
    RegenerateKeyByEmailRequest,
)
from app.components.common.schemas import Role

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login")
async def login(req: LoginRequest):
    """Admin login (single super admin from env)."""
    return await service.login(req)


@router.post("/candidate/login")
async def candidate_login(req: CandidateLoginRequest):
    """Candidate login: the access key selects Level 1 or Level 2."""
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


@router.post("/candidate/regenerate-key")
async def regenerate_key_by_email(
    req: RegenerateKeyByEmailRequest,
    _user: User = Depends(require_role(Role.INTERVIEWER)),
):
    """Regenerate access key for a candidate by email — works regardless of who originally linked them."""
    return await service.regenerate_access_key_by_email(req.email)


@router.post("/candidate/{candidate_id}/regenerate-key")
async def regenerate_key(
    candidate_id: str,
    user: User = Depends(require_role(Role.INTERVIEWER)),
):
    """Regenerate access key for a candidate by ID (legacy)."""
    return await service.regenerate_access_key(candidate_id, str(user.id))


@router.delete("/candidate/{candidate_id}")
async def delete_candidate(
    candidate_id: str,
    user: User = Depends(require_role(Role.INTERVIEWER)),
):
    """Delete a candidate."""
    return await service.delete_candidate(candidate_id, str(user.id))
