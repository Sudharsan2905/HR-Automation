"""Level 1 admin review endpoints (interviewer / super admin)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response

from app.components.auth.dependencies import require_role
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.level1 import assessment_service, scoring_tasks, version_service
from app.components.level1.db import get_db
from app.components.level1.schemas import ReaccessRequest, TerminateRequest

router = APIRouter(prefix="/level1/assessments", tags=["Level 1 Review"], dependencies=[Depends(require_role(Role.INTERVIEWER))])

Admin = Annotated[User, Depends(require_role(Role.INTERVIEWER))]


@router.get("/{assessment_id}/submissions")
async def list_submissions(
    assessment_id: str,
    search: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    sort_by: Annotated[str, Query()] = "created_at",
    sort_order: Annotated[str, Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Submissions with candidate name, email, score and status."""
    return await assessment_service.get_submissions(get_db(), assessment_id, search, sort_by, sort_order, page, page_size, status)


@router.get("/{assessment_id}/submissions/{submission_id}")
async def get_submission(assessment_id: str, submission_id: str) -> dict:
    """Full per-question review with expected answers, feedback and proctoring evidence."""
    return await assessment_service.get_submission_detail(get_db(), assessment_id, submission_id)


@router.get("/{assessment_id}/submissions/{submission_id}/media")
async def get_media(assessment_id: str, submission_id: str, key: Annotated[str, Query()]) -> Response:
    """Serve a screenshot or evidence file (raw bytes, authenticated)."""
    content, content_type = await assessment_service.get_media(get_db(), assessment_id, submission_id, key)
    return Response(content=content, media_type=content_type)


@router.get("/{assessment_id}/submissions/{submission_id}/versions")
async def list_versions(assessment_id: str, submission_id: str) -> list[dict]:
    """Archived earlier attempts (from re-access grants)."""
    return await version_service.get_versions_list(get_db(), submission_id)


@router.get("/{assessment_id}/submissions/{submission_id}/versions/{version}")
async def get_version(assessment_id: str, submission_id: str, version: int) -> dict:
    """One archived attempt with full detail."""
    return await version_service.get_version_detail(get_db(), submission_id, version)


@router.post("/{assessment_id}/submissions/{submission_id}/reaccess")
async def grant_reaccess(assessment_id: str, submission_id: str, req: ReaccessRequest, admin: Admin) -> dict:
    """Archive the attempt, reset it and issue (and email) a new Level 1 key."""
    key = await assessment_service.grant_reaccess(get_db(), assessment_id, submission_id, str(admin.id), req.reason, req.reason_category.value)
    return {"granted": True, "access_key": key}


@router.post("/{assessment_id}/submissions/{submission_id}/terminate")
async def terminate_submission(assessment_id: str, submission_id: str, req: TerminateRequest, background_tasks: BackgroundTasks) -> dict:
    """Force-terminate a live session and score what was answered."""
    db = get_db()
    current = await assessment_service.terminate_submission(db, assessment_id, submission_id, req.reason)
    background_tasks.add_task(scoring_tasks.calculate_and_store_score, db, submission_id, current)
    return {"terminated": True}


@router.post("/{assessment_id}/submissions/{submission_id}/complete")
async def complete_submission(assessment_id: str, submission_id: str, background_tasks: BackgroundTasks) -> dict:
    """Force-complete a live session and score it."""
    db = get_db()
    current = await assessment_service.complete_submission(db, assessment_id, submission_id)
    background_tasks.add_task(scoring_tasks.calculate_and_store_score, db, submission_id, current)
    return {"completed": True}


@router.post("/{assessment_id}/submissions/{submission_id}/resume")
async def resume_submission(assessment_id: str, submission_id: str, admin: Admin) -> dict:
    """Resume an ON_HOLD session."""
    await assessment_service.resume_interview(get_db(), assessment_id, submission_id, str(admin.id))
    return {"resumed": True}
