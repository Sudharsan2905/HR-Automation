from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request

from app.components.auth.dependencies import get_effective_user, require_role
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.session import service
from app.components.session.schemas import SessionStartRequest

router = APIRouter(prefix="/session", tags=["Session"])

_candidate_only = require_role(Role.CANDIDATE)


@router.post("/start")
async def start_session(request: Request, body: SessionStartRequest = Body(default=None), user: User = Depends(_candidate_only)):
    """Start or resume interview session — creates LiveKit room."""
    jti = request.state.jwt_payload.get("jti", "")
    camera_available = body.camera_available if body else True
    return await service.start_session(str(user.id), jti, camera_available=camera_available)


@router.post("/complete")
async def complete_session(
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(_candidate_only),
):
    """Complete interview — disconnect bot, close room, trigger evaluation."""
    payload = request.state.jwt_payload
    result = await service.complete_session(
        str(user.id),
        jwt_jti=payload.get("jti", ""),
        jwt_exp=payload.get("exp", 0),
    )

    from app.components.jd_interview.models import JdInterview

    # JD-based interviews get the JD-alignment report instead of the standard evaluation + emails
    if await JdInterview.find_one(JdInterview.interview_id == result["interview_id"]):
        from app.components.jd_interview.service import run_jd_report
        background_tasks.add_task(run_jd_report, result["interview_id"])
    else:
        from app.components.evaluation.service import run_evaluation
        background_tasks.add_task(run_evaluation, result["interview_id"])

    return result


@router.get("/progress")
async def get_progress(user: User = Depends(_candidate_only)):
    """Get current session progress and AI state."""
    return await service.get_progress(str(user.id))


@router.post("/next-question")
async def next_question(user: User = Depends(_candidate_only)):
    """Signal AI to speak the next question (candidate done answering)."""
    return await service.next_question(str(user.id))


# --- Audio check (lobby mic & speaker test) ---

@router.get("/audio-check")
async def get_audio_check(user: User = Depends(_candidate_only)):
    """Generate a tech joke and return TTS audio for the question (MP3, base64)."""
    return await service.get_audio_check()


# --- Interviewer endpoints ---

@router.get("/{interview_id}/watch-token")
async def get_watch_token(interview_id: str, user: User = Depends(get_effective_user)):
    """Get observer token for interviewer/admin to watch a live session."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        from fastapi import HTTPException
        raise HTTPException(403, "Insufficient permissions")
    return await service.get_watch_token(interview_id, str(user.id), is_admin=user.role == Role.SUPER_ADMIN)


@router.post("/{interview_id}/join")
async def join_session(interview_id: str, user: User = Depends(get_effective_user)):
    """Upgrade interviewer/admin from observer to active participant."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        from fastapi import HTTPException
        raise HTTPException(403, "Insufficient permissions")
    return await service.join_as_interviewer(interview_id, str(user.id), is_admin=user.role == Role.SUPER_ADMIN)


@router.post("/{interview_id}/pause-ai")
async def interviewer_pause_ai(interview_id: str, user: User = Depends(get_effective_user)):
    """Pause the AI bot."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        from fastapi import HTTPException
        raise HTTPException(403, "Insufficient permissions")
    return await service.pause_ai_by_interviewer(interview_id, str(user.id), is_admin=user.role == Role.SUPER_ADMIN)


@router.post("/{interview_id}/resume-ai")
async def interviewer_resume_ai(interview_id: str, user: User = Depends(get_effective_user)):
    """Resume the AI bot."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        from fastapi import HTTPException
        raise HTTPException(403, "Insufficient permissions")
    return await service.resume_ai_by_interviewer(interview_id, str(user.id), is_admin=user.role == Role.SUPER_ADMIN)
