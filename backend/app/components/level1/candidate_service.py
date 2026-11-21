"""Candidate exam flow: start, round, answers, malpractice strikes, screenshots, session state."""

import random
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app._core.settings import settings
from app.components.auth.models import User
from app.components.level1 import db as l1db
from app.components.level1 import storage
from app.components.level1.connection_manager import admin_manager, manager
from app.components.level1.constants import TERMINAL_STATUSES, QuestionType, SubmissionStatus
from app.components.level1.schemas import (
    AnswerSavedResponse,
    MalpracticeRecordResponse,
    SessionStateResponse,
    SubmissionStatusResponse,
)
from app.components.level1.utils import oid, serialize_doc, utcnow
from app.components.utils.logger import log

_DEFAULT_CONTENT_TYPE = "image/jpeg"
_ERR_ASSESSMENT = "Assessment not found"
_ERR_SUBMISSION = "Submission not found"
_ERR_RESTRICTED = "You are not authorized to access this assessment link."
_rng = random.SystemRandom()

_VIDEO_EVENTS = {"FACE_ABSENCE", "MULTIPLE_FACES", "EYE_DIRECTION"}
_AUDIO_EVENTS = {"AUDIO_VIOLATION", "SPEAKING", "BACKGROUND_NOISE"}
_LIVE = [SubmissionStatus.IN_PROGRESS, SubmissionStatus.ON_HOLD]


def _subs(db: AsyncIOMotorDatabase):
    return db[l1db.SUBMISSIONS]


async def _resolve_share(db: AsyncIOMotorDatabase, share_link: str) -> tuple[dict, dict]:
    share = await db[l1db.SHARES].find_one({"share_link": share_link, "is_active": True})
    assessment = None
    if share:
        assessment = await db[l1db.ASSESSMENTS].find_one({"_id": share["assessment_id"], "is_active": True})
    if not assessment:
        raise HTTPException(404, _ERR_ASSESSMENT)
    return share, assessment


async def find_my_share_link(db: AsyncIOMotorDatabase, candidate_id: str) -> str | None:
    """Share link of the newest active assessment this candidate was invited to (None if there is none)."""
    user = await User.get(candidate_id)
    email = (user.email if user else "").strip().lower()
    if not email:
        return None
    cursor = db[l1db.SHARES].find({"is_active": True, "restricted_emails": email}).sort("_id", -1)
    async for share in cursor:
        if await db[l1db.ASSESSMENTS].find_one({"_id": share["assessment_id"], "is_active": True}, {"_id": 1}):
            return share["share_link"]
    return None


async def get_candidate_assessment(db: AsyncIOMotorDatabase, share_link: str) -> dict:
    """Assessment metadata by share link, without internal question ids."""
    _, assessment = await _resolve_share(db, share_link)
    safe = serialize_doc(assessment)
    for r in safe.get("rounds", []):
        r.pop("question_ids", None)
    safe["share_link"] = share_link
    return safe


async def _handle_existing_submission(db: AsyncIOMotorDatabase, existing: dict) -> dict:
    status = existing.get("status")
    if status in TERMINAL_STATUSES:
        raise HTTPException(403, "You have already completed this assessment. Please contact admin for re-access.")
    if status in _LIVE:
        return serialize_doc(existing)
    await _subs(db).update_one(
        {"_id": existing["_id"]},
        {"$set": {"status": SubmissionStatus.IN_PROGRESS, "started_at": utcnow(), "updated_at": utcnow()}},
    )
    return serialize_doc(await _subs(db).find_one({"_id": existing["_id"]}))


def _sanitize_question(q: dict) -> dict:
    """Candidate-facing fields only; strip answers and shuffle MCQ options."""
    sq = serialize_doc(q)
    q_type = sq.get("question_type", "essay")
    options: list = []
    if q_type in (QuestionType.MCQ_SINGLE, QuestionType.MCQ_MULTI):
        options = [{k: v for k, v in o.items() if k != "is_correct"} for o in sq.get("options", [])]
        _rng.shuffle(options)
    return {
        "id": sq.get("id", ""),
        "type": "mcq_multiple" if q_type == QuestionType.MCQ_MULTI else q_type,
        "text": sq.get("question_text", ""),
        "complexity": sq.get("complexity"),
        "options": options,
    }


async def build_round_data(db: AsyncIOMotorDatabase, round_cfg: dict) -> dict:
    """Sample and sanitize questions for one round."""
    required = round_cfg["question_count"]
    question_ids = round_cfg.get("question_ids", [])
    selected = _rng.sample(question_ids, required) if len(question_ids) >= required else question_ids
    raw = await db[l1db.QUESTIONS].find({"_id": {"$in": selected}}).to_list(len(selected))
    safe = [_sanitize_question(q) for q in raw]
    _rng.shuffle(safe)
    return {
        "round_number": round_cfg["round_number"],
        "question_count": required,
        "max_duration_minutes": round_cfg["max_duration_minutes"],
        "questions": safe,
        "answers": {},
        "completed": False,
        "started_at": None,
    }


async def _check_access(share: dict, candidate_id: str) -> None:
    """Only invited candidates (restricted_emails) may use the share link."""
    if not share.get("restrict_candidate_access"):
        return
    user = await User.get(candidate_id)
    email = (user.email if user else "").strip().lower()
    if email not in (share.get("restricted_emails") or []):
        raise HTTPException(403, _ERR_RESTRICTED)


def _monitoring_details(assessment: dict) -> dict:
    cfg = assessment.get("monitoring_config") or {}
    return {
        "tab_monitoring": cfg.get("tab_monitoring", False),
        "audio_monitoring": cfg.get("audio_monitoring", False),
        "video_monitoring": cfg.get("video_monitoring", False),
        "screenshot_enabled": cfg.get("screenshot_enabled", False),
        "screenshot_mode": cfg.get("screenshot_mode", "time_interval"),
        "screenshot_interval_seconds": cfg.get("screenshot_interval_seconds"),
        "screenshot_count": cfg.get("screenshot_count"),
    }


async def _link_pipeline_candidate(db: AsyncIOMotorDatabase, assessment_id: ObjectId, candidate_id: str, submission_id: ObjectId) -> None:
    pipeline = await db[l1db.PIPELINES].find_one({"assessment_id": str(assessment_id)}, {"_id": 1})
    if not pipeline:
        return
    await db[l1db.PIPELINE_CANDIDATES].update_one(
        {"pipeline_id": pipeline["_id"], "user_id": candidate_id},
        {"$set": {"submission_id": str(submission_id), "status": "started", "updated_at": utcnow()}},
    )


async def start_assessment(db: AsyncIOMotorDatabase, share_link: str, candidate_id: str) -> dict:
    """Start or resume a candidate's submission."""
    share, assessment = await _resolve_share(db, share_link)
    await _check_access(share, candidate_id)
    existing = await _subs(db).find_one({"assessment_id": assessment["_id"], "candidate_id": ObjectId(candidate_id)})
    if existing:
        return await _handle_existing_submission(db, existing)
    rounds_data = [await build_round_data(db, cfg) for cfg in assessment.get("rounds", [])]
    now = utcnow()
    for rd in rounds_data:
        if rd.get("round_number") == 1:
            rd["started_at"] = now
    submission = {
        "assessment_id": assessment["_id"],
        "candidate_id": ObjectId(candidate_id),
        "share_id": share["_id"],
        "monitoring_details": _monitoring_details(assessment),
        "status": SubmissionStatus.IN_PROGRESS,
        "rounds_data": rounds_data,
        "current_round": 1,
        "score": 0,
        "percentage": 0.0,
        "screenshots": [],
        "malpractice_count": 0,
        "malpractice_events": [],
        "reaccess_count": 0,
        "is_active": True,
        "started_at": now,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    submission["_id"] = (await _subs(db).insert_one(submission)).inserted_id
    await _link_pipeline_candidate(db, assessment["_id"], candidate_id, submission["_id"])
    log.info("Level 1 started: candidate_id=%s submission_id=%s", candidate_id, submission["_id"])
    return serialize_doc(submission)


async def _own_submission(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str, statuses: list | None = None) -> dict:
    query: dict = {"_id": oid(submission_id, "submission id"), "candidate_id": ObjectId(candidate_id)}
    if statuses:
        query["status"] = {"$in": statuses}
    sub = await _subs(db).find_one(query)
    if not sub:
        raise HTTPException(404, _ERR_SUBMISSION)
    return sub


async def start_interview(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str) -> None:
    """Record the actual start time of the current round."""
    sub = await _own_submission(db, submission_id, candidate_id, _LIVE)
    current = sub.get("current_round", 1)
    now = utcnow()
    fields: dict = {"rounds_data.$[rd].started_at": now, "updated_at": now}
    if current == 1:
        fields["started_at"] = now
    await _subs(db).update_one({"_id": sub["_id"]}, {"$set": fields}, array_filters=[{"rd.round_number": current}])


async def get_submission_status(db: AsyncIOMotorDatabase, share_link: str, candidate_id: str) -> SubmissionStatusResponse | None:
    """Current submission status for this candidate on the share link's assessment."""
    _, assessment = await _resolve_share(db, share_link)
    sub = await _subs(db).find_one({"assessment_id": assessment["_id"], "candidate_id": ObjectId(candidate_id)})
    if not sub:
        return None
    return SubmissionStatusResponse(
        submission_id=str(sub["_id"]),
        status=str(sub.get("status", "")),
        assessment_id=str(sub["assessment_id"]),
        candidate_id=str(sub["candidate_id"]),
        current_round=sub.get("current_round", 1),
        completed_at=sub["completed_at"].isoformat() if sub.get("completed_at") else None,
        paused_at=sub["paused_at"].isoformat() if sub.get("paused_at") else None,
        malpractice_count=sub.get("malpractice_count", 0),
    )


async def get_current_round(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str) -> dict:
    """Questions and metadata for the current round (never the answers)."""
    sub = await _own_submission(db, submission_id, candidate_id)
    status = sub.get("status")
    if status == SubmissionStatus.COMPLETED:
        raise HTTPException(403, "This assessment has already been completed.")
    if status == SubmissionStatus.TERMINATED:
        raise HTTPException(403, "This session has been terminated by an administrator.")
    current = sub.get("current_round", 1)
    rounds_data = sub.get("rounds_data", [])
    if current - 1 >= len(rounds_data):
        raise HTTPException(404, "Round not found")
    rd = rounds_data[current - 1]
    eff = sub.get("monitoring_details") or {}
    return {
        "round": {
            "round_number": current,
            "questions": rd.get("questions", []),
            "max_duration_minutes": rd.get("max_duration_minutes", 30),
        },
        "tab_monitoring": eff.get("tab_monitoring", False),
        "audio_monitoring": eff.get("audio_monitoring", False),
        "video_monitoring": eff.get("video_monitoring", False),
        "screenshot_enabled": eff.get("screenshot_enabled", False),
        "screenshot_mode": eff.get("screenshot_mode", "time_interval"),
        "screenshot_interval_seconds": eff.get("screenshot_interval_seconds"),
        "screenshot_count": eff.get("screenshot_count"),
        "remaining_seconds": sub.get("remaining_seconds"),
        "current_question_idx": sub.get("current_question_idx", 0),
        "session_status": status if status else "in_progress",
    }


async def submit_answer(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str, question_id: str, answer: Any) -> AnswerSavedResponse:
    """Persist an answer for the current round."""
    sub = await _own_submission(db, submission_id, candidate_id, _LIVE)
    idx = sub.get("current_round", 1) - 1
    await _subs(db).update_one(
        {"_id": sub["_id"]}, {"$set": {f"rounds_data.{idx}.answers.{question_id}": answer, "updated_at": utcnow()}}
    )
    return AnswerSavedResponse(saved=True)


async def expire_candidate_key(candidate_id: str) -> None:
    """Invalidate the candidate's Level 1 access key (exam is over)."""
    from app.components.auth.service import expire_level1_key

    user = await User.get(candidate_id)
    if user:
        await expire_level1_key(user)


async def finish_round(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str) -> dict:
    """Mark the round complete and advance or finalise; scoring runs in the background."""
    sub = await _own_submission(db, submission_id, candidate_id)
    assessment = await db[l1db.ASSESSMENTS].find_one({"_id": sub["assessment_id"], "is_active": True})
    if not assessment:
        raise HTTPException(404, _ERR_ASSESSMENT)
    current = sub.get("current_round", 1)
    if not any(rd.get("round_number") == current for rd in sub.get("rounds_data", [])):
        raise HTTPException(404, "Round not found")
    now = utcnow()
    is_last = current >= len(assessment.get("rounds", []))
    fields: dict = {"rounds_data.$[rd].completed": True, "rounds_data.$[rd].completed_at": now, "updated_at": now}
    if is_last:
        fields.update(status=SubmissionStatus.COMPLETED, completed_at=now)
    else:
        fields.update(current_round=current + 1, remaining_seconds=None, current_question_idx=0)
    await _subs(db).update_one({"_id": sub["_id"]}, {"$set": fields}, array_filters=[{"rd.round_number": current}])
    if not is_last:
        await _subs(db).update_one(
            {"_id": sub["_id"]}, {"$set": {"rounds_data.$[nxt].started_at": now}},
            array_filters=[{"nxt.round_number": current + 1}],
        )
        return {"completed": False, "next_round": current + 1, "finished_round": current}
    await expire_candidate_key(candidate_id)
    return {"completed": True, "finished_round": current}


async def save_screenshot(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str, file_bytes: bytes, content_type: str = _DEFAULT_CONTENT_TYPE) -> None:
    """Store a screenshot on local disk and record its key on the submission."""
    sub = await _subs(db).find_one({"_id": oid(submission_id, "submission id"), "candidate_id": ObjectId(candidate_id)})
    if not sub:
        return
    round_number = sub.get("current_round", 1)
    taken_at = utcnow()
    key = storage.make_screenshot_key(submission_id, round_number, taken_at.isoformat())
    await storage.upload(file_bytes, key, content_type)
    await _subs(db).update_one(
        {"_id": sub["_id"]}, {"$push": {"screenshots": {"key": key, "round": round_number, "taken_at": taken_at}}}
    )


def _event_enabled(malpractice_type: str, monitoring: dict) -> bool:
    upper = malpractice_type.upper()
    if upper in _VIDEO_EVENTS:
        return bool(monitoring.get("video_monitoring", False))
    if upper in _AUDIO_EVENTS:
        return bool(monitoring.get("audio_monitoring", False))
    return True


async def _store_evidence(submission_id: str, round_number: int, kind: str, now: Any, monitoring: dict, files: dict) -> dict:
    keys: dict = {"screen_image_key": None, "face_image_key": None}
    wanted = [
        ("screen_image", "screen_image_key", monitoring.get("screenshot_enabled", False)),
        ("face_image", "face_image_key", monitoring.get("video_monitoring", False)),
    ]
    for field, out, enabled in wanted:
        data = files.get(field)
        if data is None or not enabled:
            continue
        content = data[0] if isinstance(data, tuple) else data
        key = storage.make_evidence_key(submission_id, round_number, kind, field, now.isoformat())
        keys[out] = await storage.upload(content, key)
    return keys


async def _persist_event(db: AsyncIOMotorDatabase, sub: dict, submission_id: str, event: dict, new_count: int, terminal: bool, now: Any) -> None:
    fields: dict = {"malpractice_count": new_count, "updated_at": now}
    if terminal:
        fields.update(status=SubmissionStatus.MALPRACTICE, completed_at=now)
    await _subs(db).update_one({"_id": sub["_id"]}, {"$set": fields, "$push": {"malpractice_events": event}})
    if terminal:
        await manager.send_json(submission_id, {"type": "terminated", "reason": "malpractice"})
    await admin_manager.broadcast_event({
        "type": "malpractice_event",
        "submission_id": submission_id,
        "event_type": event.get("type"),
        "round": event.get("round"),
        "malpractice_count": new_count,
        "is_terminal": terminal,
        "timestamp": now.isoformat(),
    })


async def flag_malpractice(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str, malpractice_type: str, file_bytes_map: dict | None = None, description: str | None = None) -> MalpracticeRecordResponse:
    """Record a malpractice strike; the final strike terminates the exam."""
    sub = await _own_submission(db, submission_id, candidate_id)
    malpractice_type = str(getattr(malpractice_type, "value", malpractice_type))
    monitoring = sub.get("monitoring_details") or {}
    round_number = sub.get("current_round", 1)
    if sub.get("status") in TERMINAL_STATUSES or not _event_enabled(malpractice_type, monitoring):
        return MalpracticeRecordResponse(
            malpractice_count=sub.get("malpractice_count", 0), is_terminal=False, current_round=round_number)
    now = utcnow()
    keys = await _store_evidence(submission_id, round_number, malpractice_type, now, monitoring, file_bytes_map or {})
    new_count = (sub.get("malpractice_count") or 0) + 1
    terminal = new_count >= settings.LEVEL1_MAX_MALPRACTICE
    event_index = len(sub.get("malpractice_events") or [])
    event = {"type": malpractice_type, "description": description or "",
             "timestamp": now, "round": round_number, "is_terminal": terminal, **keys}
    await _persist_event(db, sub, submission_id, event, new_count, terminal, now)
    if terminal:
        await expire_candidate_key(candidate_id)
    log.info("Level 1 malpractice: submission_id=%s type=%s count=%d", submission_id, malpractice_type, new_count)
    return MalpracticeRecordResponse(malpractice_count=new_count, is_terminal=terminal, event_index=event_index, current_round=round_number)


async def upload_malpractice_media(db: AsyncIOMotorDatabase, submission_id: str, event_index: int, candidate_id: str, video_bytes: bytes | None = None, audio_bytes: bytes | None = None) -> None:
    """Attach a video/audio clip to an existing malpractice event."""
    sub = await _own_submission(db, submission_id, candidate_id)
    events = sub.get("malpractice_events") or []
    if event_index < 0 or event_index >= len(events):
        raise HTTPException(422, f"Invalid event_index: {event_index}")
    event = events[event_index]
    stamp = utcnow().isoformat()
    fields: dict = {}
    for data, kind, field in ((video_bytes, "video_chunk", "screen_video_key"), (audio_bytes, "audio_clip", "audio_clip_key")):
        if data:
            key = storage.make_evidence_key(submission_id, event.get("round", 1), event.get("type", "unknown"), kind, stamp)
            fields[f"malpractice_events.{event_index}.{field}"] = await storage.upload(data, key.replace(".jpg", ".bin"))
    if fields:
        await _subs(db).update_one({"_id": sub["_id"]}, {"$set": {**fields, "updated_at": utcnow()}})


async def put_session_on_hold(db: AsyncIOMotorDatabase, submission_id: str) -> None:
    """Mark an IN_PROGRESS submission ON_HOLD after a network-loss timeout."""
    now = utcnow()
    res = await _subs(db).update_one(
        {"_id": ObjectId(submission_id), "status": SubmissionStatus.IN_PROGRESS},
        {"$set": {"status": SubmissionStatus.ON_HOLD, "paused_at": now, "updated_at": now}},
    )
    if res.modified_count:
        log.info("Level 1 session ON_HOLD: submission_id=%s", submission_id)


async def get_session_state(db: AsyncIOMotorDatabase, submission_id: str, candidate_id: str) -> SessionStateResponse:
    """Persisted timer/position so the frontend can restore after a reconnect."""
    sub = await _own_submission(db, submission_id, candidate_id)
    return SessionStateResponse(
        status=str(sub.get("status", "")),
        remaining_seconds=sub.get("remaining_seconds"),
        current_question_idx=sub.get("current_question_idx", 0),
        current_round=sub.get("current_round", 1),
    )
