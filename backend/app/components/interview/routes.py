from fastapi import APIRouter, Depends, HTTPException, Query

from app.components.auth.dependencies import get_effective_user
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.interview import service
from app.components.interview.schemas import InterviewCreateRequest

router = APIRouter(prefix="/interviews", tags=["Interview"])


@router.post("")
async def create_interview(req: InterviewCreateRequest, user: User = Depends(get_effective_user)):
    """Create interview — assign question set to candidate."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.create_interview(req, str(user.id))


@router.get("/filter-options")
async def get_filter_options(user: User = Depends(get_effective_user)):
    """Get domain filter options scoped to the current user's interviews."""
    return await service.get_interview_filter_options(user)


@router.get("")
async def list_interviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    domain: str | None = Query(None),
    domain_title: str | None = Query(None),
    candidate_search: str | None = Query(None),
    interviewer_search: str | None = Query(None),
    status: str | None = Query(None),
    user: User = Depends(get_effective_user),
):
    """List interviews — scoped by role, with optional filters and pagination."""
    if user.role == Role.SUPER_ADMIN:
        return await service.get_all_interviews(
            skip=skip, limit=limit,
            domain=domain, domain_title=domain_title,
            candidate_search=candidate_search,
            interviewer_search=interviewer_search,
            status=status,
        )
    if user.role == Role.INTERVIEWER:
        return await service.get_interviewer_interviews(
            str(user.id), skip=skip, limit=limit,
            domain=domain, domain_title=domain_title,
            candidate_search=candidate_search,
            status=status,
        )
    if user.role == Role.CANDIDATE:
        return await service.get_candidate_interviews(
            user.email, skip=skip, limit=limit,
            domain=domain, domain_title=domain_title,
            status=status,
        )
    raise HTTPException(403, "Insufficient permissions")


@router.get("/{interview_id}")
async def get_interview(interview_id: str, user: User = Depends(get_effective_user)):
    """Get interview detail."""
    return await service.get_interview_detail(interview_id, user)


@router.delete("/{interview_id}")
async def delete_interview(interview_id: str, user: User = Depends(get_effective_user)):
    """Cancel an interview."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.delete_interview(interview_id, str(user.id))
