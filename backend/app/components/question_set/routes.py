import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.components.auth.dependencies import get_effective_user
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.question_set import service
from app.components.question_set.schemas import BulkGenerateRequest, CreateQuestionSetRequest, QuestionEditRequest, SingleQuestionGenerateRequest

router = APIRouter(prefix="/question-sets", tags=["Question Sets"])


@router.post("")
async def create_question_set(req: CreateQuestionSetRequest, user: User = Depends(get_effective_user)):
    """Create an empty draft question set."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.create_question_set(req, str(user.id))


@router.get("")
async def list_question_sets(
    domain: str | None = None,
    domain_title: str | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_effective_user),
):
    """List own question sets (archive). Admin sees all. Filterable by domain/status."""
    if user.role == Role.SUPER_ADMIN:
        return await service.list_all_question_sets(domain=domain, domain_title=domain_title, status=status, skip=skip, limit=limit)
    if user.role == Role.INTERVIEWER:
        return await service.list_question_sets(str(user.id), domain=domain, domain_title=domain_title, status=status, skip=skip, limit=limit)
    raise HTTPException(403, "Insufficient permissions")


@router.get("/{qs_id}")
async def get_question_set(qs_id: str, user: User = Depends(get_effective_user)):
    """Get question set detail."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.get_question_set(qs_id, str(user.id), user.role == Role.SUPER_ADMIN)


@router.put("/{qs_id}/questions/{question_id}")
async def edit_question(
    qs_id: str,
    question_id: str,
    req: QuestionEditRequest,
    user: User = Depends(get_effective_user),
):
    """Edit a question — draft only."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.edit_question(qs_id, question_id, req, str(user.id), user.role == Role.SUPER_ADMIN)


@router.post("/{qs_id}/questions/generate-bulk")
async def generate_bulk_questions(
    qs_id: str,
    form_data: str = Form(...),
    pdf: UploadFile | None = File(None),
    user: User = Depends(get_effective_user),
):
    """AI-generate multiple questions from prompt + optional PDF."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    form = BulkGenerateRequest.model_validate(json.loads(form_data))
    return await service.generate_bulk_questions(qs_id, form.prompt_text, pdf, str(user.id), user.role == Role.SUPER_ADMIN)


@router.post("/{qs_id}/questions/generate")
async def generate_single_question(qs_id: str, req: SingleQuestionGenerateRequest, user: User = Depends(get_effective_user)):
    """AI-generate a single question from user prompt."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.generate_single_question(qs_id, req.prompt, str(user.id), user.role == Role.SUPER_ADMIN)


@router.post("/{qs_id}/questions")
async def add_question(qs_id: str, req: QuestionEditRequest, user: User = Depends(get_effective_user)):
    """Add a question — draft only."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.add_question(qs_id, req, str(user.id), user.role == Role.SUPER_ADMIN)


@router.delete("/{qs_id}/questions/{question_id}")
async def remove_question(qs_id: str, question_id: str, user: User = Depends(get_effective_user)):
    """Remove a question — draft only."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.remove_question(qs_id, question_id, str(user.id), user.role == Role.SUPER_ADMIN)


@router.put("/{qs_id}/finalize")
async def finalize_question_set(qs_id: str, user: User = Depends(get_effective_user)):
    """Mark as ready — moves to archive."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.finalize_question_set(qs_id, str(user.id), user.role == Role.SUPER_ADMIN)


@router.delete("/{qs_id}")
async def delete_question_set(qs_id: str, user: User = Depends(get_effective_user)):
    """Delete a draft question set."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")
    return await service.delete_question_set(qs_id, str(user.id), user.role == Role.SUPER_ADMIN)
