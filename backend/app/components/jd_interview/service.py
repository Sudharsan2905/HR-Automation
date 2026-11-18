import asyncio
from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import BackgroundTasks, HTTPException, UploadFile

from app._core.settings import settings
from app.components.auth.models import User
from app.components.common.schemas import DifficultyLevel, InterviewStatus, QuestionSetStatus, Role
from app.components.interview.models import Interview
from app.components.jd_interview.models import (
    AnswerQuality,
    JdInterview,
    JdProfile,
    JdReport,
    PerQuestionResult,
    SkillAlignment,
)
from app.components.jd_interview.prompt import (
    JD_GENERATION_PROMPT,
    JD_REPORT_PROMPT,
    JD_RESUME_SECTION,
    JD_SINGLE_QUESTION_PROMPT,
)
from app.components.jd_interview.schemas import LLMJdGeneration, LLMJdQuestion, LLMJdReport
from app.components.question_set.models import FollowUp, Question, QuestionSet
from app.components.utils.llm_client import get_llm_client
from app.components.utils.logger import log
from app.components.utils.resume_parser import parse_resume

JD_DOMAIN = "jd_based"
JD_DOMAIN_TITLE = "JD Interview"
MIN_JD_CHARS = 50
MIN_QUESTIONS = 5
MAX_TRANSCRIPT_CHARS = 80000
LEVELS = {"junior", "mid", "senior"}
AUTO_DIFFICULTY = {"junior": "medium", "mid": "medium", "senior": "pro"}  # junior/mid -> intermediate, senior -> advanced
VALID_TYPES = {"concept", "project", "scenario"}
LEVEL_VALUE = {"strong": 1.0, "partial": 0.5, "weak": 0.0}
VALID_RECOMMENDATIONS = {"strong_hire", "hire", "borderline", "no_hire"}


# --- Helpers ---

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_writer(user: User) -> None:
    """Only the admin (or a panel member) may write."""
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Only the admin can do this")


def _ensure_reader(user: User) -> None:
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")


async def _get_owned(jd_id: str, user: User, *, write: bool) -> JdInterview:
    try:
        jd = await JdInterview.get(jd_id)
    except Exception:
        jd = None
    if not jd:
        raise HTTPException(404, "JD interview not found")
    if write:
        _ensure_writer(user)
        if jd.created_by != str(user.id):
            raise HTTPException(403, "Not your JD interview")
    else:
        _ensure_reader(user)
        if user.role != Role.SUPER_ADMIN and jd.created_by != str(user.id):
            raise HTTPException(403, "Not your JD interview")
    return jd


async def _read_text_input(text: str | None, upload: UploadFile | None, max_chars: int, label: str) -> str:
    """Use pasted text if given, otherwise parse the uploaded PDF/DOCX."""
    value = (text or "").strip()
    if not value and upload is not None and upload.filename:
        try:
            value = (await parse_resume(upload)).strip()
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            log.warning("%s parse failed: %s", label, e)
            raise HTTPException(400, f"Could not read the {label} file")
        if not value:
            raise HTTPException(400, f"No text found in the {label} file (scanned/image-only files are not supported)")
    if len(value) > max_chars:
        raise HTTPException(400, f"{label} is too long ({len(value)} characters, max {max_chars})")
    return value


def _norm_exp_level(value: str) -> str:
    v = (value or "").strip().lower()
    if v in LEVELS:
        return v
    if v in ("lead", "staff", "principal", "architect", "sr", "senior+"):
        return "senior"
    if v in ("intermediate", "middle", "mid-level"):
        return "mid"
    if v in ("entry", "fresher", "associate", "jr", "beginner"):
        return "junior"
    return ""


def _mix(num_questions: int, has_resume: bool) -> tuple[int, int]:
    """(project questions, senior scenario questions) for a set of this size."""
    n_project = max(2, round(0.35 * num_questions)) if has_resume else 0
    n_scenario = max(1, round(0.3 * num_questions))
    return n_project, n_scenario


def _clean_question(q: LLMJdQuestion, existing_id: str | None = None) -> Question | None:
    text = (q.question or "").strip()
    if not text:
        return None
    topic = " ".join((q.topic or "General").split()[:4]) or "General"
    points = [p.strip() for p in q.expected_points if p and p.strip()][:4] or ["Clear, accurate and relevant explanation"]
    follow_ups = [FollowUp(question=f.question.strip()) for f in q.follow_ups if f.question and f.question.strip()][:2]
    kwargs = {"id": existing_id} if existing_id else {}
    return Question(question=text, topic=topic, expected_points=points, follow_ups=follow_ups, **kwargs)


def _derive_status(jd: JdInterview, qs: QuestionSet | None, interview: Interview | None) -> str:
    if jd.generation_status == "generating":
        return "generating"
    if jd.generation_status == "failed":
        return "failed"
    if interview:
        if interview.status in (InterviewStatus.COMPLETED, InterviewStatus.PARTIALLY_COMPLETED):
            if jd.report_status == "done":
                return "report_ready"
            if jd.report_status == "failed":
                return "report_failed"
            return "report_generating"
        return "in_progress" if interview.is_live else "assigned"
    if qs and qs.status == QuestionSetStatus.READY:
        return "ready"
    return "draft"


async def _load_links(jd: JdInterview) -> tuple[QuestionSet | None, Interview | None]:
    qs = await QuestionSet.get(jd.question_set_id)
    interview = None
    if jd.interview_id:
        interview = await Interview.get(jd.interview_id)
        if not interview:  # interview was deleted elsewhere -> treat as unassigned
            jd.interview_id = None
            jd.candidate_mail = None
            jd.report_status = "none"
            jd.report_id = None
            jd.report_error = None
            await jd.save()
    return qs, interview


def _summary(jd: JdInterview, qs: QuestionSet | None, interview: Interview | None) -> dict:
    return {
        "id": str(jd.id),
        "title": jd.title,
        "role_title": jd.jd_profile.role_title,
        "status": _derive_status(jd, qs, interview),
        "generation_status": jd.generation_status,
        "report_status": jd.report_status,
        "difficulty_level": jd.difficulty_level,
        "num_questions": len(qs.questions) if qs else 0,
        "has_resume": bool(jd.resume_text),
        "candidate_mail": jd.candidate_mail,
        "interview_id": jd.interview_id,
        "question_set_id": jd.question_set_id,
        "created_at": jd.created_at.isoformat(),
    }


def _question_dict(q: Question, skill_map: dict[str, str], type_map: dict[str, str] | None = None) -> dict:
    return {
        "id": q.id,
        "question": q.question,
        "topic": q.topic,
        "jd_skill": skill_map.get(q.id, ""),
        "type": (type_map or {}).get(q.id, ""),
        "expected_points": q.expected_points,
        "follow_ups": [{"id": fu.id, "question": fu.question} for fu in q.follow_ups],
    }


# --- Create + generate ---

async def create_jd_interview(
    user: User,
    background_tasks: BackgroundTasks,
    *,
    title: str | None,
    role_title: str | None,
    jd_text: str | None,
    jd_file: UploadFile | None,
    resume_text: str | None,
    resume_file: UploadFile | None,
    difficulty: str,
    num_questions: int | None,
) -> dict:
    """Validate input, create the draft question set + JD record, and generate in the background."""
    _ensure_writer(user)

    difficulty = (difficulty or "auto").strip().lower()
    if difficulty != "auto":
        try:
            DifficultyLevel(difficulty)
        except ValueError:
            raise HTTPException(400, "difficulty must be one of: auto, easy, medium, pro")

    n = num_questions or settings.JD_DEFAULT_QUESTIONS
    if n < MIN_QUESTIONS or n > settings.MAX_QUESTIONS_PER_BULK:
        raise HTTPException(400, f"num_questions must be between {MIN_QUESTIONS} and {settings.MAX_QUESTIONS_PER_BULK}")

    jd = await _read_text_input(jd_text, jd_file, settings.JD_MAX_CHARS, "JD")
    if len(jd) < MIN_JD_CHARS:
        raise HTTPException(400, "Please provide a job description (text or PDF/DOCX file)")
    resume = await _read_text_input(resume_text, resume_file, settings.RESUME_MAX_CHARS, "Resume")

    heading = (title or role_title or "").strip() or "JD Interview"
    qs = QuestionSet(
        title=heading,
        tags=[],
        created_by=str(user.id),
        difficulty_level=DifficultyLevel.MEDIUM if difficulty == "auto" else DifficultyLevel(difficulty),
        domain=JD_DOMAIN,
        domain_title=JD_DOMAIN_TITLE,
        questions=[],
    )
    await qs.insert()

    record = JdInterview(
        created_by=str(user.id),
        title=heading,
        jd_text=jd,
        resume_text=resume or None,
        resume_filename=(resume_file.filename if resume_file and resume_file.filename else None),
        difficulty_level=difficulty,
        num_questions=n,
        jd_profile=JdProfile(role_title=(role_title or "").strip()),
        question_set_id=str(qs.id),
    )
    await record.insert()

    background_tasks.add_task(run_generation, str(record.id))
    log.info("JD interview created: %s (qs=%s, n=%d)", record.id, qs.id, n)
    return _summary(record, qs, None)


async def run_generation(jd_id: str) -> None:
    """Background: analyze JD and (re)build the question set."""
    jd = await JdInterview.get(jd_id)
    if not jd:
        return
    try:
        qs = await QuestionSet.get(jd.question_set_id)
        if not qs:
            raise RuntimeError("question set missing")

        resume_section = JD_RESUME_SECTION.format(resume_text=jd.resume_text) if jd.resume_text else ""
        n_project, n_scenario = _mix(jd.num_questions, bool(jd.resume_text))
        prompt = JD_GENERATION_PROMPT.format(
            num_questions=jd.num_questions,
            jd_text=jd.jd_text,
            resume_section=resume_section,
            level=jd.difficulty_level,
            role_title=jd.jd_profile.role_title or "(none)",
            has_resume="yes" if jd.resume_text else "no",
            n_project=n_project,
            n_scenario=n_scenario,
        )
        result = await get_llm_client().generate_structured(
            prompt, LLMJdGeneration, max_tokens=settings.LLM_MAX_TOKENS_JD_GENERATION, temperature=0.7,
        )

        if not result.is_valid_jd:
            raise ValueError(result.invalid_reason or "This does not look like a job description")

        questions: list[Question] = []
        skill_map: dict[str, str] = {}
        type_map: dict[str, str] = {}
        for lq in result.questions[: jd.num_questions]:
            q = _clean_question(lq)
            if q:
                questions.append(q)
                skill_map[q.id] = (lq.jd_skill or "").strip()
                qtype = (lq.type or "concept").strip().lower()
                type_map[q.id] = qtype if qtype in VALID_TYPES else "concept"
        if not questions:
            raise ValueError("The AI returned no usable questions. Please try again.")

        p = result.jd_profile
        exp_level = _norm_exp_level(result.experience_level) or _norm_exp_level(p.seniority) or "mid"
        jd.jd_profile = JdProfile(
            role_title=p.role_title or jd.jd_profile.role_title,
            seniority=p.seniority or exp_level.capitalize(),
            experience_level=exp_level,
            level_rationale=(result.level_rationale or "").strip()[:300],
            must_have_skills=[s for s in p.must_have_skills if s][:10],
            nice_to_have_skills=[s for s in p.nice_to_have_skills if s][:8],
            responsibilities=[s for s in p.responsibilities if s][:8],
        )
        jd.question_skill_map = skill_map
        jd.question_type_map = type_map
        jd.generation_status = "done"
        jd.generation_error = None
        jd.updated_at = _now()
        await jd.save()

        effective = AUTO_DIFFICULTY[exp_level] if jd.difficulty_level == "auto" else jd.difficulty_level
        qs.difficulty_level = DifficultyLevel(effective)
        qs.questions = questions
        qs.tags = [t for t in result.tags if t][:8]
        qs.updated_at = _now()
        await qs.save()
        log.info("JD %s: generated %d questions (level=%s, difficulty=%s, types=%s)", jd_id, len(questions), exp_level, effective, {t: list(type_map.values()).count(t) for t in VALID_TYPES})
    except Exception as e:
        log.error("JD generation failed for %s: %s", jd_id, e, exc_info=True)
        jd.generation_status = "failed"
        jd.generation_error = str(e)[:300] or "Question generation failed. Please try again."
        jd.updated_at = _now()
        await jd.save()


async def regenerate(jd_id: str, question_id: str | None, user: User, background_tasks: BackgroundTasks) -> dict:
    """Regenerate the whole set (background) or replace a single question (inline)."""
    jd = await _get_owned(jd_id, user, write=True)
    qs, interview = await _load_links(jd)
    if not qs or qs.status != QuestionSetStatus.DRAFT or interview:
        raise HTTPException(400, "Questions can only be regenerated while the set is still a draft")
    if jd.generation_status == "generating":
        raise HTTPException(409, "Generation already in progress")

    if question_id is None:
        jd.generation_status = "generating"
        jd.generation_error = None
        jd.updated_at = _now()
        await jd.save()
        background_tasks.add_task(run_generation, jd_id)
        return {"message": "Regenerating all questions", "generation_status": "generating"}

    idx = next((i for i, q in enumerate(qs.questions) if q.id == question_id), None)
    if idx is None:
        raise HTTPException(404, "Question not found")
    old = qs.questions[idx]
    existing = "\n".join(f"- {q.question}" for q in qs.questions)
    old_type = jd.question_type_map.get(old.id, "concept")
    exp_level = jd.jd_profile.experience_level or "mid"
    effective = AUTO_DIFFICULTY.get(exp_level, "medium") if jd.difficulty_level == "auto" else jd.difficulty_level
    prompt = JD_SINGLE_QUESTION_PROMPT.format(
        jd_text=jd.jd_text,
        experience_level=exp_level,
        qtype=old_type,
        resume_block=jd.resume_text or "(none)",
        level=effective,
        skill=jd.question_skill_map.get(old.id, "") or "(any important JD skill)",
        old_question=old.question,
        existing=existing,
    )
    try:
        result = await get_llm_client().generate_structured(
            prompt, LLMJdQuestion, max_tokens=settings.LLM_MAX_TOKENS_SINGLE_QUESTION, temperature=0.7,
        )
    except Exception as e:
        log.error("JD single regenerate failed: %s", e)
        raise HTTPException(502, "The AI could not generate a replacement. Please try again.")
    new_q = _clean_question(result, existing_id=old.id)
    if not new_q:
        raise HTTPException(502, "The AI returned an empty question. Please try again.")
    qs.questions[idx] = new_q
    qs.updated_at = _now()
    await qs.save()
    jd.question_skill_map[new_q.id] = (result.jd_skill or "").strip()
    new_type = (result.type or old_type).strip().lower()
    jd.question_type_map[new_q.id] = new_type if new_type in VALID_TYPES else old_type
    jd.updated_at = _now()
    await jd.save()
    return {"question": _question_dict(new_q, jd.question_skill_map, jd.question_type_map)}


# --- Read ---

async def get_detail(jd_id: str, user: User) -> dict:
    jd = await _get_owned(jd_id, user, write=False)
    qs, interview = await _load_links(jd)
    data = _summary(jd, qs, interview)
    data.update({
        "jd_text": jd.jd_text,
        "resume_filename": jd.resume_filename,
        "jd_profile": jd.jd_profile.model_dump(),
        "generation_error": jd.generation_error,
        "report_error": jd.report_error,
        "question_set_status": qs.status.value if qs else None,
        "interview_status": interview.status.value if interview else None,
        "due_date": interview.due_date.isoformat() if interview and interview.due_date else None,
        "tags": qs.tags if qs else [],
        "questions": [_question_dict(q, jd.question_skill_map, jd.question_type_map) for q in qs.questions] if qs else [],
    })
    return data


async def list_jd_interviews(user: User, skip: int, limit: int, status: str | None) -> dict:
    _ensure_reader(user)
    mongo_filter = {} if user.role == Role.SUPER_ADMIN else {"created_by": str(user.id)}
    jds = await JdInterview.find(mongo_filter).sort("-created_at").to_list()

    qs_ids = [PydanticObjectId(j.question_set_id) for j in jds]
    iv_ids = [PydanticObjectId(j.interview_id) for j in jds if j.interview_id]
    qs_map = {str(q.id): q for q in await QuestionSet.find(In(QuestionSet.id, qs_ids)).to_list()} if qs_ids else {}
    iv_map = {str(i.id): i for i in await Interview.find(In(Interview.id, iv_ids)).to_list()} if iv_ids else {}

    items = []
    for j in jds:
        row = _summary(j, qs_map.get(j.question_set_id), iv_map.get(j.interview_id) if j.interview_id else None)
        if status and row["status"] != status:
            continue
        items.append(row)
    return {"total": len(items), "items": items[skip: skip + limit]}


# --- Assign / unassign / delete ---

async def assign(jd_id: str, candidate_email: str, candidate_name: str, due_date: str, user: User) -> dict:
    """Assign the finalized set to a candidate using the existing interview flow."""
    from app.components.interview.schemas import InterviewCreateRequest
    from app.components.interview.service import create_interview

    candidate_email = candidate_email.strip().lower()
    jd = await _get_owned(jd_id, user, write=True)
    qs, interview = await _load_links(jd)
    if jd.generation_status != "done" or not qs:
        raise HTTPException(400, "Questions are not ready yet")
    if qs.status != QuestionSetStatus.READY:
        raise HTTPException(400, "Finalize the question set before assigning")
    if interview:
        raise HTTPException(400, "Already assigned. Unassign first to assign to someone else")

    try:
        due = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "due_date must be an ISO date-time")

    try:
        req = InterviewCreateRequest(
            question_set_id=str(qs.id),
            candidate_email=candidate_email,
            candidate_name=candidate_name,
            due_date=due,
        )
    except ValueError:
        raise HTTPException(400, "Due date must be in the future")

    # An email that already belongs to a panel member / admin must not become a candidate account
    clash = await User.find_one(User.email == candidate_email, User.role != Role.CANDIDATE)
    if clash:
        raise HTTPException(400, "This email belongs to a panel member or admin and cannot be used as a candidate")

    created = await create_interview(req, str(user.id), include_access_key_in_email=True)
    jd.interview_id = created["id"]
    jd.candidate_mail = created["candidate_mail"]
    jd.report_status = "none"
    jd.report_id = None
    jd.updated_at = _now()
    await jd.save()
    return {
        "interview_id": created["id"],
        "candidate_mail": created["candidate_mail"],
        "access_key": created.get("access_key"),
        "email_status": created.get("email_status", "not_configured"),  # sent | not_configured | failed
        "due_date": created.get("due_date"),
    }


async def unassign(jd_id: str, user: User) -> dict:
    from app.components.interview.service import delete_interview

    jd = await _get_owned(jd_id, user, write=True)
    qs, interview = await _load_links(jd)
    if not interview:
        raise HTTPException(400, "Not assigned")
    if interview.status != InterviewStatus.FINALIZED:
        raise HTTPException(400, "Cannot unassign after the candidate has attended")
    await delete_interview(str(interview.id), str(user.id))
    jd.interview_id = None
    jd.candidate_mail = None
    jd.updated_at = _now()
    await jd.save()
    return {"message": "Unassigned"}


async def delete_jd_interview(jd_id: str, user: User) -> dict:
    jd = await _get_owned(jd_id, user, write=True)
    qs, interview = await _load_links(jd)
    if interview:
        raise HTTPException(400, "Unassign the interview before deleting")
    if jd.generation_status == "generating":
        raise HTTPException(409, "Generation in progress")
    if qs:
        await qs.delete()
    await jd.delete()
    return {"message": "JD interview deleted"}


# --- Report ---

def _truncate_transcript(text: str) -> str:
    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    half = MAX_TRANSCRIPT_CHARS // 2
    return text[:half] + "\n[... middle of transcript truncated ...]\n" + text[-half:]


def _norm_level(level: str) -> str:
    level = (level or "").strip().lower()
    return level if level in ("strong", "partial", "weak", "not_assessed") else "not_assessed"


async def run_jd_report(interview_id: str) -> None:
    """Background: build the JD-alignment report for a finished interview."""
    from app.components.session.transcript import Transcript

    jd = await JdInterview.find_one(JdInterview.interview_id == interview_id)
    if not jd:
        return
    jd.report_status = "generating"
    jd.report_error = None
    await jd.save()

    try:
        await asyncio.sleep(3)  # let trailing STT utterances land in the transcript
        interview = await Interview.get(interview_id)
        qs = await QuestionSet.get(jd.question_set_id)
        if not interview or not qs:
            raise RuntimeError("Interview or question set missing")

        transcripts = await Transcript.find(Transcript.interview_id == interview_id).sort("+timestamp").to_list()
        if not any(t.role == "candidate" for t in transcripts):
            raise RuntimeError("No candidate answers were captured in the transcript")

        candidate = await User.find_one(User.email == interview.candidate_mail)
        candidate_name = candidate.full_name if candidate and candidate.full_name else "Candidate"

        # Prepared questions to grade (skip the generic intro question)
        graded = [q for q in qs.questions if q.topic != "Introduction"]
        if not graded:
            raise RuntimeError("No questions to evaluate")
        blocks = []
        for i, q in enumerate(graded, 1):
            skill = jd.question_skill_map.get(q.id, "") or "General"
            points = "; ".join(q.expected_points)
            blocks.append(f"Q{i} (index {i}) [JD skill: {skill}]: {q.question}\n    Expected points: {points}")

        role_label = {"ai": "Suvera AI", "candidate": "Candidate", "interviewer": "Panel"}
        transcript_text = _truncate_transcript(
            "\n".join(f"[{t.timestamp.strftime('%H:%M:%S')}] {role_label.get(t.role, t.role)}: {t.text}" for t in transcripts)
        )

        prof = jd.jd_profile
        if jd.resume_text:
            resume_section = f"\n<resume>\n{jd.resume_text}\n</resume>\n"
            resume_instruction = "\"resume_consistency\": 2-3 sentences on where the candidate's answers supported or contradicted claims in the resume."
        else:
            resume_section = ""
            resume_instruction = "No resume was provided: set \"resume_consistency\" to null."

        prompt = JD_REPORT_PROMPT.format(
            role_title=prof.role_title or jd.title,
            seniority=prof.seniority or "n/a",
            must_have=", ".join(prof.must_have_skills) or "none listed",
            nice_to_have=", ".join(prof.nice_to_have_skills) or "none listed",
            responsibilities="; ".join(prof.responsibilities) or "none listed",
            questions_block="\n".join(blocks),
            resume_section=resume_section,
            resume_instruction=resume_instruction,
            transcript=transcript_text,
        )

        llm = get_llm_client()
        result = await llm.generate_structured(
            prompt, LLMJdReport, max_tokens=settings.LLM_MAX_TOKENS_JD_REPORT, temperature=0.2,
        )

        by_index = {pq.question_index: pq for pq in result.per_question}
        per_question: list[PerQuestionResult] = []
        for i, q in enumerate(graded, 1):
            pq = by_index.get(i)
            per_question.append(PerQuestionResult(
                question_id=q.id,
                question=q.question,
                jd_skill=jd.question_skill_map.get(q.id, ""),
                question_type=jd.question_type_map.get(q.id, ""),
                expected_points=q.expected_points,
                answer_summary=pq.answer_summary if pq else "Not evaluated.",
                covered_points=pq.covered_points if pq else [],
                missed_points=pq.missed_points if pq else list(q.expected_points),
                score=max(0, min(10, pq.score)) if pq else 0,
                feedback=pq.feedback if pq else "The AI did not return an evaluation for this question.",
            ))

        total = float(sum(p.score for p in per_question))
        max_score = 10.0 * len(per_question)
        score_pct = round(total / max_score * 100, 1) if max_score else 0.0

        llm_skills = {s.skill.strip().lower(): s for s in result.skill_alignment}
        alignment: list[SkillAlignment] = []
        for importance, skills in (("must_have", prof.must_have_skills), ("nice_to_have", prof.nice_to_have_skills)):
            for skill in skills:
                m = llm_skills.get(skill.strip().lower())
                alignment.append(SkillAlignment(
                    skill=skill,
                    importance=importance,
                    level=_norm_level(m.level) if m else "not_assessed",
                    evidence=m.evidence if m else "",
                ))

        total_w = assessed_w = earned = 0.0
        for a in alignment:
            w = 2.0 if a.importance == "must_have" else 1.0
            total_w += w
            if a.level in LEVEL_VALUE:
                assessed_w += w
                earned += w * LEVEL_VALUE[a.level]
        if total_w:
            jd_match = round(earned / assessed_w * 100, 1) if assessed_w else 0.0
            coverage = round(assessed_w / total_w * 100, 1)
        else:
            jd_match, coverage = score_pct, 100.0

        recommendation = result.recommendation if result.recommendation in VALID_RECOMMENDATIONS else "borderline"

        await JdReport.find(JdReport.jd_interview_id == str(jd.id)).delete()
        report = JdReport(
            jd_interview_id=str(jd.id),
            interview_id=interview_id,
            candidate_mail=interview.candidate_mail,
            candidate_name=candidate_name,
            is_partial=interview.status == InterviewStatus.PARTIALLY_COMPLETED,
            per_question=per_question,
            skill_alignment=alignment,
            answer_quality=AnswerQuality(**result.answer_quality.model_dump()),
            total_score=total,
            max_score=max_score,
            score_percentage=score_pct,
            jd_match_percentage=jd_match,
            coverage_percentage=coverage,
            recommendation=recommendation,
            overall_summary=result.overall_summary,
            strengths=result.strengths[:5],
            gaps=result.gaps[:5],
            resume_consistency=result.resume_consistency if jd.resume_text else None,
            model=settings.OPENAI_MODEL if settings.LLM_PROVIDER == "openai" else settings.GEMINI_MODEL,
        )
        await report.insert()

        jd.report_id = str(report.id)
        jd.report_status = "done"
        jd.updated_at = _now()
        await jd.save()
        log.info("JD report done: jd=%s score=%.1f/%.0f match=%.1f%%", jd.id, total, max_score, jd_match)
    except Exception as e:
        log.error("JD report failed for interview %s: %s", interview_id, e, exc_info=True)
        jd.report_status = "failed"
        jd.report_error = str(e)[:300] or "Report generation failed"
        jd.updated_at = _now()
        await jd.save()


async def regenerate_report(jd_id: str, user: User, background_tasks: BackgroundTasks) -> dict:
    jd = await _get_owned(jd_id, user, write=True)
    _, interview = await _load_links(jd)
    if not interview or interview.status not in (InterviewStatus.COMPLETED, InterviewStatus.PARTIALLY_COMPLETED):
        raise HTTPException(400, "The interview has not been completed yet")
    if jd.report_status == "generating":
        raise HTTPException(409, "Report already being generated")
    jd.report_status = "generating"
    await jd.save()
    background_tasks.add_task(run_jd_report, str(interview.id))
    return {"message": "Report is being regenerated", "report_status": "generating"}


async def get_report(jd_id: str, user: User) -> dict:
    jd = await _get_owned(jd_id, user, write=False)
    if jd.report_status != "done" or not jd.report_id:
        return {"report_status": jd.report_status, "report_error": jd.report_error, "report": None}
    report = await JdReport.get(jd.report_id)
    if not report:
        return {"report_status": "none", "report_error": None, "report": None}
    return {
        "report_status": "done",
        "report_error": None,
        "report": {
            "id": str(report.id),
            "candidate_mail": report.candidate_mail,
            "candidate_name": report.candidate_name,
            "is_partial": report.is_partial,
            "role_title": jd.jd_profile.role_title or jd.title,
            "experience_level": jd.jd_profile.experience_level,
            "level_rationale": jd.jd_profile.level_rationale,
            "per_question": [p.model_dump() for p in report.per_question],
            "skill_alignment": [s.model_dump() for s in report.skill_alignment],
            "answer_quality": report.answer_quality.model_dump(),
            "total_score": report.total_score,
            "max_score": report.max_score,
            "score_percentage": report.score_percentage,
            "jd_match_percentage": report.jd_match_percentage,
            "coverage_percentage": report.coverage_percentage,
            "recommendation": report.recommendation,
            "overall_summary": report.overall_summary,
            "strengths": report.strengths,
            "gaps": report.gaps,
            "resume_consistency": report.resume_consistency,
            "model": report.model,
            "generated_at": report.generated_at.isoformat(),
        },
    }
