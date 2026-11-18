"""Admin review of Level 1 submissions: list, detail, re-access, terminate, complete, resume."""

import re
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.components.auth.models import User
from app.components.level1 import db as l1db
from app.components.level1 import version_service
from app.components.level1.candidate_service import expire_candidate_key
from app.components.level1.connection_manager import manager
from app.components.level1.constants import QuestionType, SubmissionStatus
from app.components.level1.utils import oid, serialize_doc, utcnow
from app.components.utils.logger import log

_ERR_SUBMISSION = "Submission not found"
_MCQ = (QuestionType.MCQ_SINGLE.value, QuestionType.MCQ_MULTI.value, "mcq_multiple")
_ACTIVE = {SubmissionStatus.PENDING, SubmissionStatus.IN_PROGRESS}
_SORTABLE = {"started_at", "completed_at", "created_at", "score", "percentage", "candidate_name"}


def _media_url(assessment_id: str, submission_id: str, key: str | None) -> str | None:
    if not key:
        return None
    return f"/api/level1/assessments/{assessment_id}/submissions/{submission_id}/media?key={key}"


def _list_pipeline(assessment_id: str, status: str | None, search: str | None) -> list[dict]:
    match: dict = {"assessment_id": ObjectId(assessment_id), "is_active": {"$ne": False}}
    if status:
        match["status"] = status
    pipeline: list[dict] = [
        {"$match": match},
        {"$lookup": {"from": "users", "localField": "candidate_id", "foreignField": "_id", "as": "candidate"}},
        {"$unwind": {"path": "$candidate", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {"candidate_name": "$candidate.full_name", "candidate_email": "$candidate.email"}},
    ]
    if search:
        rx = {"$regex": re.escape(search), "$options": "i"}
        pipeline.append({"$match": {"$or": [{"candidate_name": rx}, {"candidate_email": rx}]}})
    return pipeline


async def get_submissions(db: AsyncIOMotorDatabase, assessment_id: str, search: str | None, sort_by: str, sort_order: str, page: int, page_size: int, status: str | None = None) -> dict:
    """Paginated submissions with candidate name/email (question bodies excluded)."""
    base = _list_pipeline(str(oid(assessment_id, "assessment id")), status, search)
    total_res = await db[l1db.SUBMISSIONS].aggregate(base + [{"$count": "total"}]).to_list(1)
    total = total_res[0]["total"] if total_res else 0
    sort_field = sort_by if sort_by in _SORTABLE else "created_at"
    pipeline = base + [
        {"$project": {"candidate": 0, "rounds_data": 0, "screenshots": 0, "malpractice_events": 0}},
        {"$sort": {sort_field: 1 if sort_order == "asc" else -1}},
        {"$skip": (page - 1) * page_size},
        {"$limit": page_size},
    ]
    docs = await db[l1db.SUBMISSIONS].aggregate(pipeline).to_list(page_size)
    return {
        "submissions": [serialize_doc(d) for d in docs],
        "pagination": {"total": total, "page": page, "page_size": page_size,
                       "total_pages": (total + page_size - 1) // page_size},
    }


def _question_detail(q: dict, rd: dict, original: dict) -> dict:
    qid = q.get("id", "")
    raw = (rd.get("answers") or {}).get(qid)
    answer = [raw] if isinstance(raw, str) and q.get("type") in _MCQ else raw
    result = (rd.get("question_results") or {}).get(qid) or {}
    is_mcq = q.get("type") in _MCQ
    options = original.get("options") or q.get("options") or []
    correct_ids = [o.get("id") for o in options if o.get("is_correct")] if is_mcq else []
    return {
        "id": qid,
        "type": q.get("type"),
        "text": q.get("text") or original.get("question_text", ""),
        "complexity": q.get("complexity"),
        "options": options,
        "candidate_answer": answer if answer is not None else ([] if is_mcq else ""),
        "correct_option_ids": correct_ids,
        "correct_answer": original.get("correct_answer") if not is_mcq else None,
        "is_correct": result.get("is_correct"),
        "feedback": result.get("feedback"),
    }


async def _originals(db: AsyncIOMotorDatabase, rounds: list[dict]) -> dict[str, dict]:
    qids = [ObjectId(q["id"]) for rd in rounds for q in rd.get("questions", []) if q.get("id")]
    if not qids:
        return {}
    docs = await db[l1db.QUESTIONS].find({"_id": {"$in": qids}}).to_list(len(qids))
    return {str(d["_id"]): d for d in docs}


def _round_detail(rd: dict, originals: dict[str, dict]) -> dict:
    return {
        "round_number": rd.get("round_number"),
        "max_duration_minutes": rd.get("max_duration_minutes"),
        "score": rd.get("score"),
        "percentage": rd.get("percentage"),
        "started_at": rd.get("started_at"),
        "completed_at": rd.get("completed_at"),
        "questions": [_question_detail(q, rd, originals.get(q.get("id"), {})) for q in rd.get("questions", [])],
    }


def _event_detail(e: dict, assessment_id: str, submission_id: str) -> dict:
    out = dict(e)
    for src, dst in (("screen_image_key", "screen_image_url"), ("face_image_key", "face_image_url"),
                     ("screen_video_key", "screen_video_url"), ("audio_clip_key", "audio_clip_url")):
        out[dst] = _media_url(assessment_id, submission_id, out.get(src))
    return out


async def get_submission_detail(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str) -> dict:
    """Full per-question review incl. essay expected answers, feedback and proctoring evidence."""
    sub = await db[l1db.SUBMISSIONS].find_one({"_id": oid(submission_id, "submission id"), "assessment_id": oid(assessment_id, "assessment id")})
    if not sub:
        raise HTTPException(404, _ERR_SUBMISSION)
    user = await User.get(sub["candidate_id"])
    originals = await _originals(db, sub.get("rounds_data", []))
    rounds = [_round_detail(rd, originals) for rd in sub.get("rounds_data", [])]
    summary = {k: v for k, v in sub.items() if k not in ("rounds_data", "screenshots", "malpractice_events")}
    out = serialize_doc(summary)
    out["candidate"] = {"id": str(sub["candidate_id"]), "name": user.full_name if user else None, "email": user.email if user else None}
    out["rounds"] = serialize_doc({"r": rounds})["r"]
    out["malpractice_events"] = serialize_doc({"e": [_event_detail(e, assessment_id, submission_id) for e in sub.get("malpractice_events", [])]})["e"]
    out["screenshots"] = serialize_doc({"s": [{**s, "url": _media_url(assessment_id, submission_id, s.get("key"))} for s in sub.get("screenshots", [])]})["s"]
    return out


async def get_media(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str, key: str) -> tuple[bytes, str]:
    """Return evidence bytes only if ``key`` belongs to this submission."""
    from app.components.level1 import storage

    sub = await db[l1db.SUBMISSIONS].find_one({"_id": oid(submission_id, "submission id"), "assessment_id": oid(assessment_id, "assessment id")})
    if not sub:
        raise HTTPException(404, _ERR_SUBMISSION)
    owned = {s.get("key") for s in sub.get("screenshots", [])}
    for e in sub.get("malpractice_events", []):
        owned.update(v for k, v in e.items() if k.endswith("_key") and v)
    if key not in owned:
        raise HTTPException(404, "File not found")
    return await storage.get_bytes(key)


async def _get_sub(db: AsyncIOMotorDatabase, submission_id: str, assessment_id: str) -> dict:
    sub = await db[l1db.SUBMISSIONS].find_one({"_id": oid(submission_id, "submission id"), "assessment_id": oid(assessment_id, "assessment id")})
    if not sub:
        raise HTTPException(404, _ERR_SUBMISSION)
    return sub


async def grant_reaccess(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str, admin_id: str, reason: str, reason_category: str) -> str:
    """Archive the attempt, reset it, and issue a fresh Level 1 key (returned)."""
    from app.components.auth.service import issue_level1_key
    from app.components.level1.invite_service import build_invite_html, exam_url
    from app.components.level1.mailer import send_email

    sub = await _get_sub(db, submission_id, assessment_id)
    await version_service.grant_reaccess_with_archive(db, submission_id, admin_id, reason, reason_category)
    user = await User.get(sub["candidate_id"])
    if not user:
        raise HTTPException(404, "Candidate not found")
    key = await issue_level1_key(user)
    share = await db[l1db.SHARES].find_one({"assessment_id": sub["assessment_id"], "is_active": True})
    assessment = await db[l1db.ASSESSMENTS].find_one({"_id": sub["assessment_id"]})
    if share and assessment:
        body = build_invite_html(user.full_name or "", assessment["name"], exam_url(share["share_link"]), user.email, key)
        await send_email(user.email, f"Assessment re-access: {assessment['name']}", body)
    log.info("Level 1 re-access granted: submission_id=%s", submission_id)
    return key


async def _end_session(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str, status: SubmissionStatus, verb: str) -> int:
    sub = await _get_sub(db, submission_id, assessment_id)
    if sub.get("status") not in _ACTIVE:
        raise HTTPException(403, f"Cannot {verb} a submission with status '{sub.get('status')}'. Only pending or in-progress submissions can be {verb}d.")
    now = utcnow()
    await db[l1db.SUBMISSIONS].update_one({"_id": sub["_id"]}, {"$set": {"status": status, "completed_at": now, "updated_at": now}})
    await expire_candidate_key(str(sub["candidate_id"]))
    return int(sub.get("current_round", 1))


async def terminate_submission(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str, reason: str) -> int:
    """Admin force-terminate; returns the round to score."""
    current = await _end_session(db, assessment_id, submission_id, SubmissionStatus.TERMINATED, "terminate")
    await manager.send_json(submission_id, {"type": "terminated", "reason": "admin"})
    log.info("Level 1 session terminated: submission_id=%s reason=%s", submission_id, reason)
    return current


async def complete_submission(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str) -> int:
    """Admin force-complete; returns the round to score."""
    return await _end_session(db, assessment_id, submission_id, SubmissionStatus.COMPLETED, "complete")


async def resume_interview(db: AsyncIOMotorDatabase, assessment_id: str, submission_id: str, admin_id: str) -> None:
    """Resume an ON_HOLD session and notify the candidate if online."""
    sub = await _get_sub(db, submission_id, assessment_id)
    if sub.get("status") != SubmissionStatus.ON_HOLD:
        raise HTTPException(403, f"Cannot resume a submission with status '{sub.get('status')}'. Only ON_HOLD submissions can be resumed.")
    now = utcnow()
    await db[l1db.SUBMISSIONS].update_one({"_id": sub["_id"]}, {"$set": {"status": SubmissionStatus.IN_PROGRESS, "resumed_at": now, "updated_at": now}})
    log.info("Level 1 resumed: submission_id=%s admin_id=%s", submission_id, admin_id)
    payload: dict[str, Any] = {"type": "resume_approved", "remaining_seconds": sub.get("remaining_seconds"), "current_question_idx": sub.get("current_question_idx", 0)}
    await manager.send_json(submission_id, payload)
