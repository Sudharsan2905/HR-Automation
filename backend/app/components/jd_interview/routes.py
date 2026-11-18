from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile

from app.components.auth.dependencies import get_effective_user
from app.components.auth.models import User
from app.components.jd_interview import service
from app.components.jd_interview.schemas import AssignRequest, RegenerateRequest

router = APIRouter(prefix="/jd-interviews", tags=["JD Interviews"])


@router.post("")
async def create_jd_interview(
    background_tasks: BackgroundTasks,
    title: str | None = Form(None),
    role_title: str | None = Form(None),
    jd_text: str | None = Form(None),
    resume_text: str | None = Form(None),
    difficulty: str = Form("auto"),
    num_questions: int | None = Form(None),
    jd_file: UploadFile | None = File(None),
    resume_file: UploadFile | None = File(None),
    user: User = Depends(get_effective_user),
):
    """Submit a JD (+ optional resume); questions are generated in the background."""
    return await service.create_jd_interview(
        user, background_tasks,
        title=title, role_title=role_title, jd_text=jd_text, jd_file=jd_file,
        resume_text=resume_text, resume_file=resume_file,
        difficulty=difficulty, num_questions=num_questions,
    )


@router.get("")
async def list_jd_interviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: str | None = None,
    user: User = Depends(get_effective_user),
):
    """List JD interviews (own; admin sees all)."""
    return await service.list_jd_interviews(user, skip, limit, status)


@router.get("/{jd_id}")
async def get_jd_interview(jd_id: str, user: User = Depends(get_effective_user)):
    """Detail: status, JD profile, questions, assignment."""
    return await service.get_detail(jd_id, user)


@router.post("/{jd_id}/regenerate")
async def regenerate(jd_id: str, background_tasks: BackgroundTasks, req: RegenerateRequest | None = None, user: User = Depends(get_effective_user)):
    """Regenerate all questions (background) or one question (inline)."""
    return await service.regenerate(jd_id, req.question_id if req else None, user, background_tasks)


@router.post("/{jd_id}/assign")
async def assign(jd_id: str, req: AssignRequest, user: User = Depends(get_effective_user)):
    """Assign the finalized set to a candidate."""
    return await service.assign(jd_id, req.candidate_email, req.candidate_name, req.due_date, user)


@router.post("/{jd_id}/unassign")
async def unassign(jd_id: str, user: User = Depends(get_effective_user)):
    """Remove the assignment (only before the candidate attends)."""
    return await service.unassign(jd_id, user)


@router.get("/{jd_id}/report")
async def get_report(jd_id: str, user: User = Depends(get_effective_user)):
    """JD-alignment report for the candidate's interview."""
    return await service.get_report(jd_id, user)


@router.post("/{jd_id}/report/regenerate")
async def regenerate_report(jd_id: str, background_tasks: BackgroundTasks, user: User = Depends(get_effective_user)):
    """Re-run report generation from the stored transcript."""
    return await service.regenerate_report(jd_id, user, background_tasks)


@router.delete("/{jd_id}")
async def delete_jd_interview(jd_id: str, user: User = Depends(get_effective_user)):
    """Delete an unassigned JD interview and its draft question set."""
    return await service.delete_jd_interview(jd_id, user)
