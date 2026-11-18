from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.components.auth.dependencies import get_effective_user
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.evaluation import service

router = APIRouter(prefix="/evaluations", tags=["Evaluation"])


@router.get("/interviewer/all")
async def all_interviewer_evaluations(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    candidate_search: str | None = None,
    max_percentage: float | None = Query(None, ge=0, le=100),
    user: User = Depends(get_effective_user),
):
    """List all evaluations for interviews created by this interviewer."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.get_evaluations_by_interviewer(
        str(user.id), skip=skip, limit=limit,
        candidate_search=candidate_search, max_percentage=max_percentage,
    )


@router.get("/{interview_id}")
async def get_evaluation(interview_id: str, user: User = Depends(get_effective_user)):
    """View evaluation result for an interview."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")

    evaluation = await service.get_evaluation(interview_id)
    if not evaluation:
        raise HTTPException(404, "Evaluation not found or still processing")

    if user.role == Role.INTERVIEWER and evaluation.interviewer_id != str(user.id):
        raise HTTPException(403, "Not your interview")

    return evaluation.model_dump(mode="json")


@router.get("/{interview_id}/report")
async def download_report(interview_id: str, user: User = Depends(get_effective_user)):
    """Download suvera_insights.pdf evaluation report."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")

    evaluation = await service.get_evaluation(interview_id)
    if not evaluation:
        raise HTTPException(404, "Evaluation not found")

    if user.role == Role.INTERVIEWER and evaluation.interviewer_id != str(user.id):
        raise HTTPException(403, "Not your interview")

    if not evaluation.pdf_report_path or not Path(evaluation.pdf_report_path).exists():
        raise HTTPException(404, "PDF report not yet generated")

    return FileResponse(
        evaluation.pdf_report_path,
        media_type="application/pdf",
        filename=f"suvera_insights_{interview_id}.pdf",
    )


@router.get("/{interview_id}/transcript")
async def download_transcript(interview_id: str, user: User = Depends(get_effective_user)):
    """Download raw_conversation.pdf transcript."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")

    evaluation = await service.get_evaluation(interview_id)
    if not evaluation:
        raise HTTPException(404, "Evaluation not found")

    if user.role == Role.INTERVIEWER and evaluation.interviewer_id != str(user.id):
        raise HTTPException(403, "Not your interview")

    if not evaluation.conversation_pdf_path or not Path(evaluation.conversation_pdf_path).exists():
        raise HTTPException(404, "Transcript PDF not yet generated")

    return FileResponse(
        evaluation.conversation_pdf_path,
        media_type="application/pdf",
        filename=f"raw_conversation_{interview_id}.pdf",
    )
