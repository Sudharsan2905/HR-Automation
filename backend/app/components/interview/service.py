import re
import secrets
from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import HTTPException

from app.components.auth.models import User
from app.components.auth.service import _name_from_email
from app.components.common.schemas import InterviewStatus, QuestionSetStatus, Role, UserStatus
from app.components.interview.models import Interview
from app.components.interview.schemas import InterviewCreateRequest
from app.components.question_set.models import QuestionSet
from app.components.session.transcript import Transcript
from app.components.utils.logger import log


async def create_interview(form: InterviewCreateRequest, interviewer_id: str, *, include_access_key_in_email: bool = False) -> dict:
    """Create interview — assign a ready question set to a candidate."""
    qs = await QuestionSet.get(form.question_set_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if qs.created_by != interviewer_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.READY:
        raise HTTPException(400, "Question set must be finalized before assigning")

    # Resolve candidate: by ID, or get-or-create by email
    if form.candidate_id:
        candidate = await User.get(form.candidate_id)
        if not candidate or candidate.role != Role.CANDIDATE:
            raise HTTPException(404, "Candidate not found")
    elif form.candidate_email:
        candidate = await User.find_one(User.email == form.candidate_email, User.role == Role.CANDIDATE)
        if not candidate:
            candidate = User(
                email=form.candidate_email,
                role=Role.CANDIDATE,
                status=UserStatus.ACTIVE,
                full_name=form.candidate_name or _name_from_email(form.candidate_email),
                created_by=interviewer_id,
            )
            await candidate.insert()
            log.info("Candidate auto-created: %s", form.candidate_email)
    else:
        raise HTTPException(400, "Provide candidate_id or candidate_email")

    # Generate access key if the candidate doesn't have one or it was already used
    access_key = candidate.access_key
    if not access_key or candidate.access_key_used:
        access_key = secrets.token_urlsafe(16)
        candidate.access_key = access_key
        candidate.access_key_used = False
        await candidate.save()

    interview = Interview(
        interviewer_id=interviewer_id,
        candidate_mail=candidate.email,
        question_set_id=str(qs.id),
        due_date=form.due_date,
    )
    await interview.insert()

    email_status = "not_configured"
    try:
        from app.components.utils.email_client import get_email_client

        interviewer_user = await User.get(interviewer_id)
        email_client = get_email_client()
        if email_client:
            await email_client.send_interview_scheduled(
                to=candidate.email,
                candidate_name=candidate.full_name or "Candidate",
                due_date=f"{form.due_date.day} {form.due_date.strftime('%B %Y (%A)')}" if hasattr(form.due_date, "strftime") else str(form.due_date),
                skill_sets=qs.tags,
                interviewer_name=interviewer_user.full_name if interviewer_user else "Your Interviewer",
                interviewer_email=interviewer_user.email if interviewer_user else None,
                access_key=access_key if include_access_key_in_email else None,
            )
            email_status = "sent"
    except Exception as e:
        email_status = "failed"
        log.warning("Failed to send schedule email: %s", e)

    log.info("Interview created: %s (candidate=%s)", interview.id, candidate.email)
    detail = _interview_to_detail(interview, qs, candidate)
    detail["access_key"] = access_key
    detail["email_status"] = email_status
    return detail


# --- Filters ---

async def _build_filter(
    interviewer_id: str | None = None,
    candidate_email: str | None = None,
    domain: str | None = None,
    domain_title: str | None = None,
    candidate_search: str | None = None,
    interviewer_search: str | None = None,
) -> dict | None:
    """Build a MongoDB filter dict. Returns None if the filter would yield zero results."""
    mongo_filter: dict = {}

    if interviewer_id:
        mongo_filter["interviewer_id"] = interviewer_id
    if candidate_email:
        mongo_filter["candidate_mail"] = candidate_email

    # QuestionSet-based domain filters
    if domain or domain_title:
        qs_query: dict = {}
        if domain:
            qs_query["domain"] = domain
        if domain_title:
            qs_query["domain_title"] = domain_title
        qs_ids = [str(qs.id) for qs in await QuestionSet.find(qs_query).to_list()]
        if not qs_ids:
            return None
        mongo_filter["question_set_id"] = {"$in": qs_ids}

    # Candidate text search (name or email, case-insensitive)
    if candidate_search:
        escaped = re.escape(candidate_search)
        matched = await User.find({
            "role": Role.CANDIDATE.value,
            "$or": [
                {"full_name": {"$regex": escaped, "$options": "i"}},
                {"email": {"$regex": escaped, "$options": "i"}},
            ],
        }).to_list()
        emails = [u.email for u in matched]
        if not emails:
            return None
        existing = mongo_filter.get("candidate_mail")
        if isinstance(existing, str):
            if existing not in emails:
                return None
        else:
            mongo_filter["candidate_mail"] = {"$in": emails}

    # Interviewer text search (admin only; name or email, case-insensitive)
    if interviewer_search:
        escaped = re.escape(interviewer_search)
        matched = await User.find({
            "role": Role.INTERVIEWER.value,
            "$or": [
                {"full_name": {"$regex": escaped, "$options": "i"}},
                {"email": {"$regex": escaped, "$options": "i"}},
            ],
        }).to_list()
        ids = [str(u.id) for u in matched]
        if not ids:
            return None
        existing = mongo_filter.get("interviewer_id")
        if isinstance(existing, str):
            if existing not in ids:
                return None
        else:
            mongo_filter["interviewer_id"] = {"$in": ids}

    return mongo_filter


# --- List helpers ---

async def _batch_load_qs(interviews: list[Interview]) -> dict[str, QuestionSet]:
    """Batch-load question sets for a list of interviews."""
    qs_ids = list({i.question_set_id for i in interviews})
    if not qs_ids:
        return {}
    qs_list = await QuestionSet.find({"_id": {"$in": [PydanticObjectId(qid) for qid in qs_ids]}}).to_list()
    return {str(qs.id): qs for qs in qs_list}


async def _batch_load_names(interviews: list[Interview]) -> dict[str, str]:
    """Batch-load candidate names by email."""
    emails = list({i.candidate_mail for i in interviews})
    if not emails:
        return {}
    users = await User.find({"email": {"$in": emails}, "role": Role.CANDIDATE}).to_list()
    return {u.email: u.full_name or u.email for u in users}


def _empty_result() -> dict:
    return {"total": 0, "items": [], "status_counts": {}}


async def _aggregate(document_class, pipeline: list) -> list[dict]:
    """Run a MongoDB aggregation pipeline via Motor directly (Beanie 2.x + Motor 3.x compatible)."""
    col = document_class.get_motor_collection()
    cursor = col.aggregate(pipeline)
    return await cursor.to_list(length=None)


async def _query_with_counts(
    base_filter: dict,
    status: str | None,
    skip: int,
    limit: int,
) -> dict:
    """Run status-count aggregation + paginated item query, return combined result."""
    # Status distribution for the full base filter (without status restriction)
    agg_pipeline = [
        {"$match": base_filter},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    status_rows = await _aggregate(Interview, agg_pipeline)
    status_counts: dict[str, int] = {row["_id"]: row["count"] for row in status_rows}

    # Apply status filter on top for the actual item query
    item_filter = {**base_filter}
    if status:
        item_filter["status"] = status

    total = status_counts.get(status, 0) if status else sum(status_counts.values())

    interviews = await Interview.find(item_filter).sort("-created_at").skip(skip).limit(limit).to_list()
    qs_map = await _batch_load_qs(interviews)
    name_map = await _batch_load_names(interviews)

    return {
        "total": total,
        "items": [_interview_to_summary(i, qs_map.get(i.question_set_id), name_map) for i in interviews],
        "status_counts": status_counts,
    }


async def get_interviewer_interviews(
    interviewer_id: str,
    skip: int = 0,
    limit: int = 100,
    domain: str | None = None,
    domain_title: str | None = None,
    candidate_search: str | None = None,
    status: str | None = None,
) -> dict:
    """List all interviews created by this interviewer, with optional filters."""
    base_filter = await _build_filter(
        interviewer_id=interviewer_id,
        domain=domain,
        domain_title=domain_title,
        candidate_search=candidate_search,
    )
    if base_filter is None:
        return _empty_result()
    return await _query_with_counts(base_filter, status, skip, limit)


async def get_candidate_interviews(
    email: str,
    skip: int = 0,
    limit: int = 100,
    domain: str | None = None,
    domain_title: str | None = None,
    status: str | None = None,
) -> dict:
    """Interviews assigned to a specific candidate."""
    base_filter = await _build_filter(
        candidate_email=email,
        domain=domain,
        domain_title=domain_title,
    )
    if base_filter is None:
        return _empty_result()
    return await _query_with_counts(base_filter, status, skip, limit)


async def get_all_interviews(
    skip: int = 0,
    limit: int = 100,
    domain: str | None = None,
    domain_title: str | None = None,
    candidate_search: str | None = None,
    interviewer_search: str | None = None,
    status: str | None = None,
) -> dict:
    """All interviews — for super admin."""
    base_filter = await _build_filter(
        domain=domain,
        domain_title=domain_title,
        candidate_search=candidate_search,
        interviewer_search=interviewer_search,
    )
    if base_filter is None:
        return _empty_result()
    return await _query_with_counts(base_filter, status, skip, limit)


async def get_interview_filter_options(user: User) -> dict:
    """Return unique domain_title options scoped to the current user's interviews."""
    if user.role == Role.SUPER_ADMIN:
        base_filter: dict = {}
    elif user.role == Role.INTERVIEWER:
        base_filter = {"interviewer_id": str(user.id)}
    elif user.role == Role.CANDIDATE:
        base_filter = {"candidate_mail": user.email}
    else:
        raise HTTPException(403, "Insufficient permissions")

    # Unique question_set_ids via aggregation
    qs_id_rows = await _aggregate(Interview, [
        {"$match": base_filter},
        {"$group": {"_id": "$question_set_id"}},
    ])
    qs_ids = [row["_id"] for row in qs_id_rows if row["_id"]]

    if not qs_ids:
        return {"domain_titles": []}

    qs_list = await QuestionSet.find(
        {"_id": {"$in": [PydanticObjectId(qid) for qid in qs_ids]}}
    ).to_list()

    seen: set[str] = set()
    result: list[dict] = []
    for qs in qs_list:
        if qs.domain_title and qs.domain_title not in seen:
            seen.add(qs.domain_title)
            result.append({"domain": qs.domain, "domain_title": qs.domain_title})

    result.sort(key=lambda x: (x.get("domain") or "", x.get("domain_title") or ""))
    return {"domain_titles": result}


async def get_interview_detail(interview_id: str, user: User) -> dict:
    """Get full interview detail — enforces ownership."""
    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")

    if user.role == Role.INTERVIEWER and interview.interviewer_id != str(user.id):
        raise HTTPException(403, "Not your interview")
    if user.role == Role.CANDIDATE and interview.candidate_mail != user.email:
        raise HTTPException(403, "Not your interview")

    qs = await QuestionSet.get(interview.question_set_id)
    candidate = await User.find_one({"email": interview.candidate_mail, "role": Role.CANDIDATE})
    return _interview_to_detail(interview, qs, candidate)


async def delete_interview(interview_id: str, interviewer_id: str) -> dict:
    """Delete an interview — blocked only when live. Cleans up sessions, transcripts, and evaluations."""
    from app.components.session.models import SessionLog
    from app.components.evaluation.models import EvaluationResult

    interview = await Interview.get(interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if interview.interviewer_id != interviewer_id:
        raise HTTPException(403, "Not your interview")
    if interview.is_live:
        raise HTTPException(400, "Cannot delete a live interview")

    iid = str(interview.id)

    # Deactivate any active sessions referencing this interview
    await SessionLog.find(
        SessionLog.interview_id == iid,
        SessionLog.is_active == True,
    ).update({"$set": {"is_active": False, "completed_at": datetime.now(timezone.utc)}})

    # Remove orphaned transcripts and evaluations
    await Transcript.find(Transcript.interview_id == iid).delete()
    await EvaluationResult.find(EvaluationResult.interview_id == iid).delete()

    await interview.delete()
    log.info("Interview deleted with cleanup: %s (sessions, transcripts, evaluations removed)", iid)
    return {"message": "Interview deleted"}


# --- Serialization ---

def _interview_to_summary(interview: Interview, qs: QuestionSet | None, name_map: dict[str, str] | None = None) -> dict:
    return {
        "id": str(interview.id),
        "candidate_mail": interview.candidate_mail,
        "candidate_name": (name_map or {}).get(interview.candidate_mail, interview.candidate_mail),
        "question_set_id": interview.question_set_id,
        "tags": qs.tags if qs else [],
        "domain": qs.domain if qs else None,
        "domain_title": qs.domain_title if qs else None,
        "difficulty_level": qs.difficulty_level.value if qs else None,
        "num_questions": len(qs.questions) if qs else 0,
        "status": interview.status.value,
        "is_live": interview.is_live,
        "due_date": interview.due_date.isoformat() if interview.due_date else None,
        "created_at": interview.created_at.isoformat(),
    }


def _interview_to_detail(interview: Interview, qs: QuestionSet | None, candidate: User | None = None) -> dict:
    base = {
        "id": str(interview.id),
        "interviewer_id": interview.interviewer_id,
        "candidate_mail": interview.candidate_mail,
        "candidate_name": (candidate.full_name or interview.candidate_mail) if candidate else interview.candidate_mail,
        "question_set_id": interview.question_set_id,
        "status": interview.status.value,
        "is_live": interview.is_live,
        "due_date": interview.due_date.isoformat() if interview.due_date else None,
        "created_at": interview.created_at.isoformat(),
    }
    if qs:
        base.update({
            "title": qs.title,
            "tags": qs.tags,
            "domain": qs.domain,
            "domain_title": qs.domain_title,
            "difficulty_level": qs.difficulty_level.value,
            "num_questions": len(qs.questions),
            "questions": [
                {
                    "id": q.id,
                    "question": q.question,
                    "topic": q.topic,
                    "expected_points": q.expected_points,
                    "follow_ups": [{"id": fu.id, "question": fu.question} for fu in q.follow_ups],
                }
                for q in qs.questions
            ],
        })
    return base
