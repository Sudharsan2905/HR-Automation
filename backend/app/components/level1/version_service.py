"""Attempt history: archive a submission before granting re-access."""

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app._core.settings import settings
from app.components.level1 import db as l1db
from app.components.level1.constants import TERMINAL_STATUSES, SubmissionStatus
from app.components.level1.utils import oid, serialize_doc, utcnow

_ERR_SUBMISSION = "Submission not found"


def _iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _snapshot_question(q: dict, rd: dict, original: dict) -> dict:
    qid = q.get("id", "")
    result = (rd.get("question_results") or {}).get(qid) or {}
    return {
        "id": qid,
        "type": q.get("type"),
        "text": q.get("text"),
        "options": original.get("options") or q.get("options") or [],
        "candidate_answer": (rd.get("answers") or {}).get(qid),
        "correct_answer": original.get("correct_answer"),
        "is_correct": result.get("is_correct"),
        "feedback": result.get("feedback"),
    }


async def build_round_snapshot(rounds_data: list, db: AsyncIOMotorDatabase) -> list:
    """Embed question text, answers and results so history survives re-sampling."""
    qids = [ObjectId(q["id"]) for rd in rounds_data for q in rd.get("questions", []) if q.get("id")]
    docs = await db[l1db.QUESTIONS].find({"_id": {"$in": qids}}).to_list(len(qids)) if qids else []
    originals = {str(d["_id"]): d for d in docs}
    return [
        {
            "round_number": rd.get("round_number"),
            "score": rd.get("score"),
            "percentage": rd.get("percentage"),
            "question_answers": [_snapshot_question(q, rd, originals.get(q.get("id"), {})) for q in rd.get("questions", [])],
        }
        for rd in rounds_data
    ]


async def get_versions_list(db: AsyncIOMotorDatabase, submission_id: str) -> list[dict]:
    """Summary of archived attempts, oldest first."""
    docs = await db[l1db.VERSION_HISTORY].find({"submission_id": oid(submission_id, "submission id")}).sort("version", 1).to_list(None)
    return [
        {
            "version": d.get("version"), "status": d.get("status"), "score": d.get("score", 0),
            "percentage": d.get("percentage", 0.0), "malpractice_count": d.get("malpractice_count", 0),
            "reaccess_reason": d.get("reaccess_reason"), "reaccess_reason_category": d.get("reaccess_reason_category"),
            "started_at": _iso(d.get("started_at")), "completed_at": _iso(d.get("completed_at")),
        }
        for d in docs
    ]


async def get_version_detail(db: AsyncIOMotorDatabase, submission_id: str, version: int) -> dict:
    """One archived attempt with full question detail."""
    doc = await db[l1db.VERSION_HISTORY].find_one({"submission_id": oid(submission_id, "submission id"), "version": version})
    if not doc:
        raise HTTPException(404, "Version not found")
    return serialize_doc(doc)


async def archive_submission(db: AsyncIOMotorDatabase, sub: dict, admin_id: str, reason: str, reason_category: str) -> int:
    """Archive the current attempt; returns its 1-based version number."""
    version = int(sub.get("reaccess_count", 0)) + 1
    doc = {
        "submission_id": sub["_id"],
        "assessment_id": sub.get("assessment_id"),
        "candidate_id": sub.get("candidate_id"),
        "version": version,
        "status": sub.get("status"),
        "score": sub.get("score", 0),
        "percentage": sub.get("percentage", 0.0),
        "malpractice_count": sub.get("malpractice_count", 0),
        "malpractice_events": sub.get("malpractice_events", []),
        "screenshots": sub.get("screenshots", []),
        "rounds": await build_round_snapshot(sub.get("rounds_data", []), db),
        "reaccess_reason": reason,
        "reaccess_reason_category": reason_category,
        "archived_by": admin_id,
        "started_at": sub.get("started_at"),
        "completed_at": sub.get("completed_at"),
        "monitoring_details": sub.get("monitoring_details"),
        "archived_at": utcnow(),
    }
    await db[l1db.VERSION_HISTORY].insert_one(doc)
    return version


def _check_reaccess_allowed(sub: dict) -> None:
    if sub.get("reaccess_count", 0) >= settings.LEVEL1_MAX_REACCESS:
        raise HTTPException(403, f"Maximum re-access count ({settings.LEVEL1_MAX_REACCESS}) already reached.")
    if sub.get("status") not in TERMINAL_STATUSES:
        raise HTTPException(
            403,
            f"Cannot grant re-access to a submission with status '{sub.get('status')}'. "
            "Only completed, malpractice, or terminated submissions are eligible.",
        )


async def grant_reaccess_with_archive(db: AsyncIOMotorDatabase, submission_id: str, admin_id: str, reason: str, reason_category: str) -> None:
    """Archive the attempt and reset the submission to PENDING with freshly sampled questions."""
    from app.components.level1.candidate_service import build_round_data

    sub = await db[l1db.SUBMISSIONS].find_one({"_id": oid(submission_id, "submission id")})
    if not sub:
        raise HTTPException(404, _ERR_SUBMISSION)
    _check_reaccess_allowed(sub)
    assessment = await db[l1db.ASSESSMENTS].find_one({"_id": sub["assessment_id"], "is_active": True})
    if not assessment:
        raise HTTPException(404, "Assessment not found")
    version = await archive_submission(db, sub, admin_id, reason, reason_category)
    rounds_data = [await build_round_data(db, cfg) for cfg in assessment.get("rounds", [])]
    await db[l1db.SUBMISSIONS].update_one(
        {"_id": sub["_id"]},
        {"$set": {
            "status": SubmissionStatus.PENDING, "rounds_data": rounds_data, "current_round": 1,
            "malpractice_count": 0, "malpractice_events": [], "score": 0, "percentage": 0.0,
            "remaining_seconds": None, "current_question_idx": 0, "reaccess_count": version,
            "screenshots": [], "completed_at": None, "updated_at": utcnow(),
        }},
    )
