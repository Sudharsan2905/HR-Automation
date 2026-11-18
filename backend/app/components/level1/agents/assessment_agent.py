"""Assessment agent (deterministic): category + questions + assessment + restricted share."""

import secrets

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.components.level1 import db as l1db
from app.components.level1.utils import utcnow

MONITORING_DEFAULTS = {
    "tab_monitoring": True,
    "audio_monitoring": True,
    "video_monitoring": True,
    "screenshot_enabled": True,
    "screenshot_mode": "time_interval",
    "screenshot_interval_seconds": 30,
    "screenshot_count": None,
}


def _essays_without_answer(questions: list[dict]) -> list[str]:
    return [
        q["question_text"][:60]
        for q in questions
        if q["question_type"] == "essay" and not (q.get("correct_answer") or "").strip()
    ]


async def _create_category(db: AsyncIOMotorDatabase, jd_title: str, user_id: str) -> ObjectId:
    now = utcnow()
    doc = {
        "name": f"{jd_title} (AI) {now:%Y-%m-%d %H:%M:%S}",
        "description": f"AI-generated for JD: {jd_title}",
        "question_count": 0,
        "created_by": user_id,
        "created_at": now,
    }
    return (await db[l1db.CATEGORIES].insert_one(doc)).inserted_id


def _question_doc(q: dict, category_id: ObjectId, user_id: str, now) -> dict:
    return {
        "category_id": category_id,
        "question_text": q["question_text"],
        "question_type": q["question_type"],
        "complexity": q["complexity"],
        "options": q.get("options") or [],
        "correct_answer": q.get("correct_answer"),
        "created_by": user_id,
        "created_at": now,
        "updated_at": now,
    }


async def build_assessment(
    db: AsyncIOMotorDatabase,
    *,
    hiring_jd_id: str,
    user_id: str,
    jd_title: str,
    questions: list[dict],
    candidate_emails: list[str],
    duration_minutes: int,
) -> dict:
    """Create the category, insert questions, create one assessment and one share link."""
    missing = _essays_without_answer(questions)
    if missing:
        raise ValueError(f"Essay questions without a model answer: {missing}")
    category_id = await _create_category(db, jd_title, user_id)
    now = utcnow()
    docs = [_question_doc(q, category_id, user_id, now) for q in questions]
    inserted = await db[l1db.QUESTIONS].insert_many(docs)
    await db[l1db.CATEGORIES].update_one({"_id": category_id}, {"$set": {"question_count": len(docs)}})
    assessment = {
        "name": jd_title,
        "description": f"AI-generated assessment for {jd_title}",
        "hiring_jd_id": hiring_jd_id,
        "monitoring_config": dict(MONITORING_DEFAULTS),
        "rounds": [
            {
                "round_number": 1,
                "question_count": len(docs),
                "max_duration_minutes": duration_minutes,
                "question_ids": list(inserted.inserted_ids),
            }
        ],
        "created_by": user_id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    assessment_id = (await db[l1db.ASSESSMENTS].insert_one(assessment)).inserted_id
    share = {
        "assessment_id": assessment_id,
        "label": f"{jd_title} - invited candidates",
        "share_link": secrets.token_urlsafe(24),
        "restrict_candidate_access": True,
        "restricted_emails": [e.lower() for e in candidate_emails],
        "is_active": True,
        "created_by": user_id,
        "created_at": now,
    }
    share_id = (await db[l1db.SHARES].insert_one(share)).inserted_id
    return {
        "category_id": str(category_id),
        "assessment_id": str(assessment_id),
        "share_id": str(share_id),
        "share_link": share["share_link"],
    }
