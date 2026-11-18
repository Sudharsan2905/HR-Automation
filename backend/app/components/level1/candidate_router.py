"""Level 1 candidate exam endpoints (Level 1 access-key tokens only)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile

from app._core.settings import settings
from app.components.auth.dependencies import require_level1_candidate
from app.components.auth.models import User
from app.components.level1 import candidate_service, scoring_tasks
from app.components.level1.constants import MalpracticeType
from app.components.level1.db import get_db
from app.components.level1.schemas import (
    AnswerSavedResponse,
    MalpracticeRecordResponse,
    SessionStateResponse,
    SubmissionStatusResponse,
    SubmitAnswerRequest,
)

router = APIRouter(prefix="/level1/exam", tags=["Level 1 Exam"], dependencies=[Depends(require_level1_candidate)])

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
_ALLOWED_VIDEO_TYPES = {"video/webm", "video/mp4"}
_ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mpeg"}
_MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
_MAX_VIDEO_BYTES = 50 * 1024 * 1024
_MAX_AUDIO_BYTES = 10 * 1024 * 1024

Candidate = Annotated[User, Depends(require_level1_candidate)]


async def _read_upload(upload: UploadFile | None, allowed: set[str], max_bytes: int, field: str) -> bytes | None:
    if upload is None:
        return None
    if (upload.content_type or "").split(";")[0].strip() not in allowed:
        raise HTTPException(422, f"{field} has invalid content type")
    content = await upload.read()
    if len(content) > max_bytes:
        raise HTTPException(422, f"{field} exceeds size limit")
    return content


@router.get("/assessment/{share_link}")
async def get_assessment(share_link: str, user: Candidate) -> dict:
    """Assessment metadata for the share link."""
    return await candidate_service.get_candidate_assessment(get_db(), share_link)


@router.post("/assessment/{share_link}/start")
async def start_assessment(share_link: str, user: Candidate) -> dict:
    """Start or resume the exam (restricted to invited emails)."""
    return await candidate_service.start_assessment(get_db(), share_link, str(user.id))


@router.get("/submission/status", response_model=SubmissionStatusResponse | None)
async def get_submission_status(share_link: Annotated[str, Query()], user: Candidate):
    """Current submission status for the share link (null before start)."""
    return await candidate_service.get_submission_status(get_db(), share_link, str(user.id))


@router.get("/submission/{submission_id}/round")
async def get_current_round(submission_id: str, user: Candidate) -> dict:
    """Questions and monitoring config of the current round."""
    return await candidate_service.get_current_round(get_db(), submission_id, str(user.id))


@router.post("/submission/{submission_id}/answer", response_model=AnswerSavedResponse)
async def submit_answer(submission_id: str, req: SubmitAnswerRequest, user: Candidate):
    """Persist one answer."""
    return await candidate_service.submit_answer(get_db(), submission_id, str(user.id), req.question_id, req.answer)


@router.post("/submission/{submission_id}/start-round")
async def start_round(submission_id: str, user: Candidate) -> dict:
    """Record the actual start of the current round."""
    await candidate_service.start_interview(get_db(), submission_id, str(user.id))
    return {"started": True}


@router.post("/submission/{submission_id}/finish-round")
async def finish_round(submission_id: str, background_tasks: BackgroundTasks, user: Candidate) -> dict:
    """Finish the round; scoring runs in the background."""
    db = get_db()
    result = await candidate_service.finish_round(db, submission_id, str(user.id))
    finished = result.pop("finished_round")
    background_tasks.add_task(scoring_tasks.calculate_and_store_score, db, submission_id, finished)
    return result


@router.post("/submission/{submission_id}/screenshot")
async def save_screenshot(submission_id: str, user: Candidate, file: Annotated[UploadFile, File()]) -> dict:
    """Store a periodic proctoring screenshot."""
    content = await _read_upload(file, _ALLOWED_IMAGE_TYPES, _MAX_SCREENSHOT_BYTES, "file")
    await candidate_service.save_screenshot(get_db(), submission_id, str(user.id), content or b"", file.content_type or "image/jpeg")
    return {"saved": True}


@router.post("/submission/{submission_id}/malpractice", response_model=MalpracticeRecordResponse)
async def flag_malpractice(
    submission_id: str,
    background_tasks: BackgroundTasks,
    user: Candidate,
    type: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
    screen_image: Annotated[UploadFile | None, File()] = None,
    face_image: Annotated[UploadFile | None, File()] = None,
):
    """Record a malpractice strike (the final strike ends the exam)."""
    try:
        malpractice_type = MalpracticeType(type)
    except ValueError as err:
        raise HTTPException(422, f"Invalid malpractice type: {type!r}") from err
    files: dict = {}
    for field, upload in (("screen_image", screen_image), ("face_image", face_image)):
        content = await _read_upload(upload, _ALLOWED_IMAGE_TYPES, _MAX_SCREENSHOT_BYTES, field)
        if content is not None:
            files[field] = (content, upload.content_type)
    db = get_db()
    result = await candidate_service.flag_malpractice(db, submission_id, str(user.id), malpractice_type, files, description)
    if result.is_terminal:
        background_tasks.add_task(scoring_tasks.calculate_and_store_score, db, submission_id, result.current_round)
    return result


@router.post("/submission/{submission_id}/malpractice/{event_index}/media")
async def upload_malpractice_media(
    submission_id: str,
    event_index: int,
    user: Candidate,
    video_chunk: Annotated[UploadFile | None, File()] = None,
    audio_clip: Annotated[UploadFile | None, File()] = None,
) -> dict:
    """Attach a video/audio clip to an existing malpractice event."""
    video = await _read_upload(video_chunk, _ALLOWED_VIDEO_TYPES, _MAX_VIDEO_BYTES, "video_chunk")
    audio = await _read_upload(audio_clip, _ALLOWED_AUDIO_TYPES, _MAX_AUDIO_BYTES, "audio_clip")
    await candidate_service.upload_malpractice_media(get_db(), submission_id, event_index, str(user.id), video, audio)
    return {"saved": True}


@router.get("/submission/{submission_id}/session-state", response_model=SessionStateResponse)
async def get_session_state(submission_id: str, user: Candidate):
    """Persisted timer and question position."""
    return await candidate_service.get_session_state(get_db(), submission_id, str(user.id))


@router.get("/config")
async def exam_config(user: Candidate) -> dict:
    """Exam limits the frontend needs (strikes allowed, hold delay)."""
    return {"max_malpractice": settings.LEVEL1_MAX_MALPRACTICE, "hold_delay_seconds": settings.LEVEL1_HOLD_DELAY_SECONDS}
