import json
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile

from app._core.settings import settings
from app.components.common.schemas import QuestionSetStatus
from app.components.question_set.models import FollowUp, Question, QuestionSet
from app.components.question_set.schemas import (
    CreateQuestionSetRequest,
    LLMQuestion,
    LLMQuestionResponse,
    QuestionEditRequest,
)
from app.components.interview.prompt import QUESTION_GENERATION_PROMPT, SINGLE_QUESTION_PROMPT
from app.components.question_set.guardrail import run_guardrail
from app.components.utils.llm_client import get_llm_client
from app.components.utils.logger import log
from app.components.utils.resume_parser import parse_resume
from app.components.common.enums import DOMAIN_REGISTRY

async def validate_domain(domain: str, domain_title: str) -> None:
    """Check domain / title against the built-in registry."""
    titles = {d["title"] for umbrella, items in DOMAIN_REGISTRY.items() if umbrella.value == domain for d in items}
    if domain_title not in titles:
        raise HTTPException(400, f"Unknown domain: {domain} / {domain_title}")


JD_DOMAIN = "jd_based"  # domain used by JD-generated question sets (see jd_interview module)


async def create_question_set(form: CreateQuestionSetRequest, user_id: str) -> dict:
    """Create an empty draft question set."""
    await validate_domain(form.domain, form.domain_title)

    qs = QuestionSet(
        title=form.title,
        tags=form.tags,
        created_by=user_id,
        difficulty_level=form.difficulty_level,
        domain=form.domain,
        domain_title=form.domain_title,
        questions=[],
    )
    await qs.insert()

    log.info("QuestionSet created: %s", qs.id)
    return _qs_to_detail(qs)


async def _qs_aggregate(pipeline: list) -> list[dict]:
    col = QuestionSet.get_motor_collection()
    cursor = col.aggregate(pipeline)
    return await cursor.to_list(length=None)


async def list_question_sets(
    user_id: str,
    domain: str | None = None,
    domain_title: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> dict:
    """List interviewer's own question sets, optionally filtered by domain/status."""
    base: dict = {"created_by": user_id, "belongs_to_vault": False}
    if domain:
        base["domain"] = domain
    else:
        base["domain"] = {"$ne": JD_DOMAIN}  # JD-generated sets are managed in the JD Interviews module
    if domain_title:
        base["domain_title"] = domain_title

    status_rows = await _qs_aggregate([{"$match": base}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}])
    status_counts: dict[str, int] = {row["_id"]: row["count"] for row in status_rows}
    total = status_counts.get(status, 0) if status else sum(status_counts.values())

    filters = [QuestionSet.created_by == user_id, QuestionSet.belongs_to_vault == False]
    if domain:
        filters.append(QuestionSet.domain == domain)
    else:
        filters.append(QuestionSet.domain != JD_DOMAIN)
    if domain_title:
        filters.append(QuestionSet.domain_title == domain_title)
    if status:
        filters.append(QuestionSet.status == QuestionSetStatus(status))

    sets = await QuestionSet.find(*filters).sort("-created_at").skip(skip).limit(limit).to_list()
    return {"total": total, "items": [_qs_to_summary(qs) for qs in sets], "status_counts": status_counts}


async def list_all_question_sets(
    domain: str | None = None,
    domain_title: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> dict:
    """Admin: list all non-vault question sets, optionally filtered."""
    base: dict = {"belongs_to_vault": False}
    if domain:
        base["domain"] = domain
    else:
        base["domain"] = {"$ne": JD_DOMAIN}
    if domain_title:
        base["domain_title"] = domain_title

    status_rows = await _qs_aggregate([{"$match": base}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}])
    status_counts: dict[str, int] = {row["_id"]: row["count"] for row in status_rows}
    total = status_counts.get(status, 0) if status else sum(status_counts.values())

    filters = [QuestionSet.belongs_to_vault == False]
    if domain:
        filters.append(QuestionSet.domain == domain)
    else:
        filters.append(QuestionSet.domain != JD_DOMAIN)
    if domain_title:
        filters.append(QuestionSet.domain_title == domain_title)
    if status:
        filters.append(QuestionSet.status == QuestionSetStatus(status))

    sets = await QuestionSet.find(*filters).sort("-created_at").skip(skip).limit(limit).to_list()
    return {"total": total, "items": [_qs_to_summary(qs) for qs in sets], "status_counts": status_counts}


async def get_question_set(qs_id: str, user_id: str, is_admin: bool) -> dict:
    """Get question set detail with ownership check."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    return _qs_to_detail(qs)


async def edit_question(qs_id: str, question_id: str, req: QuestionEditRequest, user_id: str, is_admin: bool = False) -> dict:
    """Edit a single question — only allowed in DRAFT status."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.DRAFT:
        raise HTTPException(400, "Cannot edit — question set is no longer in draft")

    question = next((q for q in qs.questions if q.id == question_id), None)
    if not question:
        raise HTTPException(404, "Question not found")

    if req.question is not None:
        if not req.question.strip():
            raise HTTPException(400, "Question text cannot be empty")
        question.question = req.question.strip()
    if req.topic is not None:
        if not req.topic.strip():
            raise HTTPException(400, "Topic cannot be empty")
        question.topic = req.topic.strip()
    if req.expected_points is not None:
        cleaned = [p for p in req.expected_points if p.strip()]
        if not cleaned:
            raise HTTPException(400, "At least one expected point is required")
        question.expected_points = cleaned
    if req.follow_ups is not None:
        question.follow_ups = [FollowUp(question=fu.question) for fu in req.follow_ups]

    qs.updated_at = datetime.now(timezone.utc)
    await qs.save()

    return _question_to_dict(question)


async def add_question(qs_id: str, req: QuestionEditRequest, user_id: str, is_admin: bool = False) -> dict:
    """Add a question to a draft question set."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.DRAFT:
        raise HTTPException(400, "Cannot add — question set is no longer in draft")

    if not req.question or not req.question.strip():
        raise HTTPException(400, "Question text is required")
    if not req.topic or not req.topic.strip():
        raise HTTPException(400, "Topic is required")
    if not req.expected_points or not [p for p in req.expected_points if p.strip()]:
        raise HTTPException(400, "At least one expected point is required")

    question = Question(
        question=req.question.strip(),
        topic=req.topic.strip(),
        expected_points=[p for p in req.expected_points if p.strip()],
        follow_ups=[FollowUp(question=fu.question) for fu in req.follow_ups] if req.follow_ups else [],
    )
    qs.questions.append(question)
    qs.updated_at = datetime.now(timezone.utc)
    await qs.save()

    return _question_to_dict(question)


async def remove_question(qs_id: str, question_id: str, user_id: str, is_admin: bool = False) -> dict:
    """Remove a question from a draft question set."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.DRAFT:
        raise HTTPException(400, "Cannot remove — question set is no longer in draft")

    original_len = len(qs.questions)
    qs.questions = [q for q in qs.questions if q.id != question_id]
    if len(qs.questions) == original_len:
        raise HTTPException(404, "Question not found")

    qs.updated_at = datetime.now(timezone.utc)
    await qs.save()

    return {"message": "Question removed"}


INTRO_QUESTION_TEXT = (
    "Hey there!, I'm Suvera AI from Softsuave Technologies. "
    "Excited to meet you! Tell me about yourself so we can get started."
)


async def finalize_question_set(qs_id: str, user_id: str, is_admin: bool = False) -> dict:
    """Mark question set as ready (archived for reuse)."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.DRAFT:
        raise HTTPException(400, f"Already {qs.status.value}")
    if len(qs.questions) < 5:
        raise HTTPException(400, "A question set must have at least 5 questions to finalize")

    # Prepend intro question for non-vault question sets (skip if already present from a fork)
    already_has_intro = qs.questions and qs.questions[0].question == INTRO_QUESTION_TEXT
    if not qs.belongs_to_vault and not already_has_intro:
        intro = Question(
            question=INTRO_QUESTION_TEXT,
            topic="Introduction",
            expected_points=["Self-introduction", "Background summary"],
            follow_ups=[],
        )
        qs.questions.insert(0, intro)

    qs.status = QuestionSetStatus.READY
    qs.updated_at = datetime.now(timezone.utc)
    await qs.save()

    return {"message": "Question set finalized", "status": qs.status.value}


async def generate_single_question(qs_id: str, prompt: str, user_id: str, is_admin: bool = False) -> dict:
    """Use LLM to generate a single question from user prompt, scoped to QS metadata."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.DRAFT:
        raise HTTPException(400, "Cannot add — question set is no longer in draft")

    guardrail = await run_guardrail(prompt, qs.domain, qs.domain_title, single=True)
    if guardrail.action == "rejected":
        return {"status": "rejected", "message": guardrail.message or "Request was rejected."}
    if guardrail.action == "answered":
        return {"status": "answered", "message": guardrail.message}

    formatted = SINGLE_QUESTION_PROMPT.format(
        domain=qs.domain,
        domain_title=qs.domain_title,
        user_prompt=prompt,
        tags=", ".join(qs.tags) or "General",
        difficulty=qs.difficulty_level.value,
    )

    llm = get_llm_client()
    result = await llm.generate_structured(formatted, LLMQuestion, max_tokens=settings.LLM_MAX_TOKENS_SINGLE_QUESTION)

    return {
        "status": "ok",
        "question": {
            "question": result.question,
            "topic": result.topic,
            "expected_points": result.expected_points,
            "follow_ups": [fu.question for fu in result.follow_ups],
        },
    }


async def generate_bulk_questions(qs_id: str, prompt_text: str, pdf_file: UploadFile | None, user_id: str, is_admin: bool = False) -> dict:
    """Generate multiple questions via LLM and append to an existing draft QS."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.status != QuestionSetStatus.DRAFT:
        raise HTTPException(400, "Cannot add — question set is no longer in draft")

    guardrail = await run_guardrail(
        prompt_text, qs.domain, qs.domain_title,
        bulk=True, current_count=len(qs.questions),
    )
    if guardrail.action == "rejected":
        return {"status": "rejected", "message": guardrail.message or "Request was rejected."}
    if guardrail.action == "answered":
        return {"status": "answered", "message": guardrail.message}

    resume_text = ""
    if pdf_file:
        resume_text = await parse_resume(pdf_file)
        if not resume_text.strip():
            raise HTTPException(400, "Could not extract text from PDF")

    resume_section = f"\n=== REFERENCE DOCUMENT ===\n{resume_text}" if resume_text else ""
    existing_questions_section = _build_existing_questions_section(qs.questions)
    prompt = QUESTION_GENERATION_PROMPT.format(
        num_questions=guardrail.num_questions,
        prompt_text=prompt_text,
        resume_section=resume_section,
        existing_questions_section=existing_questions_section,
        level=qs.difficulty_level.value,
    )

    llm = get_llm_client()
    llm_response = await llm.generate_structured(prompt, LLMQuestionResponse, max_tokens=settings.LLM_MAX_TOKENS_BULK_QUESTIONS)

    new_questions = [
        Question(
            question=q.question,
            topic=q.topic,
            expected_points=q.expected_points,
            follow_ups=[FollowUp(question=fu.question) for fu in q.follow_ups],
        )
        for q in llm_response.questions
    ]

    qs.questions.extend(new_questions)
    qs.updated_at = datetime.now(timezone.utc)
    await qs.save()

    log.info("Bulk generated %d questions for QS %s", len(new_questions), qs_id)
    return {
        "status": "ok",
        "questions_added": len(new_questions),
        "total_questions": len(qs.questions),
        "questions": [_question_to_dict(q) for q in new_questions],
        "info": guardrail.info,
    }


async def delete_question_set(qs_id: str, user_id: str, is_admin: bool = False) -> dict:
    """Delete a question set (draft or ready)."""
    qs = await QuestionSet.get(qs_id)
    if not qs:
        raise HTTPException(404, "Question set not found")
    if not is_admin and qs.created_by != user_id:
        raise HTTPException(403, "Not your question set")
    if qs.belongs_to_vault and not is_admin:
        raise HTTPException(400, "Vault contributions cannot be deleted")

    await qs.delete()
    return {"message": f"Question set '{qs.title}' deleted"}


# --- Helpers ---

def _qs_to_summary(qs: QuestionSet) -> dict:
    return {
        "id": str(qs.id),
        "title": qs.title,
        "tags": qs.tags,
        "difficulty_level": qs.difficulty_level.value,
        "domain": qs.domain,
        "domain_title": qs.domain_title,
        "num_questions": len(qs.questions),
        "status": qs.status.value,
        "forked_from": qs.forked_from,
        "created_at": qs.created_at.isoformat(),
    }


def _qs_to_detail(qs: QuestionSet) -> dict:
    return {
        **_qs_to_summary(qs),
        "created_by": qs.created_by,
        "questions": [_question_to_dict(q) for q in qs.questions],
    }


def _question_to_dict(q: Question) -> dict:
    return {
        "id": q.id,
        "question": q.question,
        "topic": q.topic,
        "expected_points": q.expected_points,
        "follow_ups": [{"id": fu.id, "question": fu.question} for fu in q.follow_ups],
    }


def _build_existing_questions_section(questions: list[Question]) -> str:
    """Build existing questions context for the LLM (question + follow_ups only)."""
    if not questions:
        return ""
    existing = [
        {
            "question": q.question,
            "follow_ups": [fu.question for fu in q.follow_ups],
        }
        for q in questions
    ]
    return f"\n=== EXISTING QUESTIONS (do NOT repeat or rephrase these) ===\n{json.dumps(existing, indent=2)}"
