"""Orchestrates: intake -> analyze (per candidate) -> questions (once) -> assessment -> invites."""

import asyncio
import hashlib

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app._core.settings import settings
from app.components.level1 import contact_extractor, mailer
from app.components.level1 import db as l1db
from app.components.level1.agents import analysis_agent, assessment_agent, question_agent
from app.components.level1.invite_service import send_invites
from app.components.level1.utils import oid, serialize_doc, utcnow
from app.components.utils.logger import log

_HIDDEN = {"profile_text": 0}
_MIN_TEXT = 30

STEP_CATALOG = [
    {
        "key": "intake",
        "agent": "Profile Intake Agent",
        "title": "Read candidate profiles and resolve contacts",
        "description": "Collects each candidate's profile text and resolves the email and name.",
    },
    {
        "key": "analysis",
        "agent": "Candidate Analysis Agent",
        "title": "Compare every candidate with the JD",
        "description": "LLM scores skill match, gaps and interview focus topics per candidate.",
    },
    {
        "key": "questions",
        "agent": "Question Architect Agent",
        "title": "Generate the shared exam",
        "description": "One LLM call builds the single-answer, multi-answer and essay questions "
        "from the JD and the candidate pool, then validates them.",
    },
    {
        "key": "assessment",
        "agent": "Assessment Builder Agent",
        "title": "Create category, assessment and secure link",
        "description": "Saves the questions, creates the assessment and an email-restricted "
        "proctored share link.",
    },
    {
        "key": "invites",
        "agent": "Invitation Dispatch Agent",
        "title": "Issue access keys and email the candidates",
        "description": "Emails each candidate one private message with the exam link, "
        "username and Level 1 access key.",
    },
]

_tasks: set[asyncio.Task] = set()


def _new_steps(total: int) -> list[dict]:
    return [
        {**s, "status": "pending", "started_at": None, "finished_at": None,
         "progress": {"done": 0, "total": total}, "detail": None, "error": None}
        for s in STEP_CATALOG
    ]


async def step_update(db: AsyncIOMotorDatabase, pid: ObjectId, key: str, **fields: object) -> None:
    """Update one step of the run's step tracker."""
    now = utcnow()
    if fields.get("status") == "running":
        fields["started_at"] = now
    if fields.get("status") in ("done", "failed", "skipped"):
        fields["finished_at"] = now
    await db[l1db.PIPELINES].update_one(
        {"_id": pid, "steps.key": key},
        {"$set": {f"steps.$.{k}": v for k, v in fields.items()} | {"updated_at": now}},
    )


async def step_progress(db: AsyncIOMotorDatabase, pid: ObjectId, key: str) -> None:
    """Increment a step's done counter."""
    await db[l1db.PIPELINES].update_one({"_id": pid, "steps.key": key}, {"$inc": {"steps.$.progress.done": 1}})


async def log_event(db: AsyncIOMotorDatabase, pid: ObjectId, step: str, message: str, level: str = "info") -> None:
    """Append to the live activity feed (capped at the last 300 events)."""
    event = {"ts": utcnow().isoformat(), "step": step, "level": level, "message": message}
    await db[l1db.PIPELINES].update_one(
        {"_id": pid}, {"$push": {"events": {"$each": [event], "$slice": -300}}}
    )


def _candidate_doc(pid: ObjectId, c: dict, now) -> dict:
    return {
        "pipeline_id": pid,
        "user_id": str(c["user_id"]),
        "name": c.get("name"),
        "email": (c.get("email") or "").strip().lower() or None,
        "email_source": "user" if c.get("email") else None,
        "description": c.get("description") or "",
        "profile_text": c.get("profile_text") or "",
        "profile_text_hash": None,
        "analysis": None,
        "submission_id": None,
        "status": "queued",
        "invite_status": "pending",
        "report_status": "pending",
        "error": None,
        "failed_step": None,
        "created_at": now,
        "updated_at": now,
    }


async def _insert_candidates(db: AsyncIOMotorDatabase, pid: ObjectId, candidates: list[dict]) -> list[dict]:
    now = utcnow()
    docs = [_candidate_doc(pid, c, now) for c in candidates]
    ins = await db[l1db.PIPELINE_CANDIDATES].insert_many(docs)
    for d, _id in zip(docs, ins.inserted_ids, strict=True):
        d["_id"] = _id
    return docs


async def _set_candidate(db: AsyncIOMotorDatabase, cid: ObjectId, **fields: object) -> None:
    await db[l1db.PIPELINE_CANDIDATES].update_one({"_id": cid}, {"$set": {**fields, "updated_at": utcnow()}})


def _label(cand: dict) -> str:
    return cand.get("name") or cand.get("email") or str(cand["_id"])


def _profile_text(cand: dict) -> str:
    text = (cand.get("profile_text") or "").strip() or (cand.get("description") or "").strip()
    if len(text) >= _MIN_TEXT:
        return text[:12000]
    return f"Candidate {cand.get('name') or ''} ({cand.get('email') or ''}). No profile details were provided."


async def _intake_candidate(db: AsyncIOMotorDatabase, sem: asyncio.Semaphore, pid: ObjectId, cand: dict) -> None:
    async with sem:
        try:
            text = _profile_text(cand)
            email, source = (cand["email"], cand["email_source"]) if cand.get("email") else contact_extractor.resolve_email(text, cand["description"])
            name = cand.get("name") or contact_extractor.find_name(text, cand["description"])
            await _set_candidate(
                db, cand["_id"], profile_text=text, profile_text_hash=hashlib.sha256(text.encode()).hexdigest(),
                email=email, email_source=source, name=name, status="parsed",
            )
            if email:
                await log_event(db, pid, "intake", f"{name or email}: email {email} found in {source}")
            else:
                await log_event(db, pid, "intake", f"{name or cand['user_id']}: no email on record", "warn")
        except Exception as exc:
            await _set_candidate(db, cand["_id"], status="failed", failed_step="intake", error=str(exc)[:300])
            await log_event(db, pid, "intake", f"{_label(cand)}: {str(exc)[:200]}", "error")
        finally:
            await step_progress(db, pid, "intake")


async def _analyze_candidate(
    db: AsyncIOMotorDatabase, sem: asyncio.Semaphore, jd_text: str, pid: ObjectId, cand_id: ObjectId, cache: dict[str, dict]
) -> None:
    async with sem:
        cand = await db[l1db.PIPELINE_CANDIDATES].find_one({"_id": cand_id})
        try:
            digest = cand["profile_text_hash"]
            cached = digest in cache
            if not cached:
                cache[digest] = (await analysis_agent.analyze_candidate(jd_text, cand["profile_text"], cand["description"])).model_dump()
            analysis = cache[digest]
            name = cand.get("name") or analysis.get("name") or (cand["email"].split("@")[0] if cand.get("email") else "Candidate")
            await _set_candidate(db, cand_id, analysis=analysis, name=name,
                                 status="analyzed" if cand.get("email") else "needs_email")
            note = " (reused identical profile)" if cached else ""
            await log_event(db, pid, "analysis", f"{name}: match {analysis['match_score']}%{note}")
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            await _set_candidate(db, cand_id, status="failed", failed_step="analysis", error=str(detail)[:400])
            await log_event(db, pid, "analysis", f"{_label(cand)}: {str(detail)[:240]}", "error")
        finally:
            await step_progress(db, pid, "analysis")


class StepFailureError(Exception):
    def __init__(self, step: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.step, self.message, self.detail = step, message, detail


async def _first_error(db: AsyncIOMotorDatabase, query: dict) -> str:
    doc = await db[l1db.PIPELINE_CANDIDATES].find_one(query)
    return (doc or {}).get("error") or ""


async def _run_intake(db: AsyncIOMotorDatabase, pid: ObjectId, sem: asyncio.Semaphore, cands: list[dict]) -> int:
    await db[l1db.PIPELINES].update_one({"_id": pid}, {"$set": {"status": "running"}})
    await step_update(db, pid, "intake", status="running")
    await log_event(db, pid, "intake", f"Reading {len(cands)} profile(s)")
    await asyncio.gather(*(_intake_candidate(db, sem, pid, c) for c in cands))
    parsed = await db[l1db.PIPELINE_CANDIDATES].count_documents({"pipeline_id": pid, "status": "parsed"})
    if not parsed:
        raise StepFailureError("intake", "No candidate profile could be read.", await _first_error(db, {"pipeline_id": pid, "error": {"$ne": None}}))
    await step_update(db, pid, "intake", status="done", detail=f"{parsed}/{len(cands)} parsed")
    return parsed


async def _run_analysis(db: AsyncIOMotorDatabase, pid: ObjectId, sem: asyncio.Semaphore, jd_text: str, parsed: int) -> list[dict]:
    await step_update(db, pid, "analysis", status="running", progress={"done": 0, "total": parsed})
    ids = [c["_id"] for c in await db[l1db.PIPELINE_CANDIDATES].find({"pipeline_id": pid, "status": "parsed"}, {"_id": 1}).to_list(None)]
    cache: dict[str, dict] = {}
    await asyncio.gather(*(_analyze_candidate(db, sem, jd_text, pid, i, cache) for i in ids))
    ok = await db[l1db.PIPELINE_CANDIDATES].find({"pipeline_id": pid, "analysis": {"$ne": None}}).to_list(None)
    if not ok:
        err = await _first_error(db, {"pipeline_id": pid, "failed_step": "analysis"})
        raise StepFailureError("analysis", f"All {len(ids)} candidate analyses failed.", err)
    await step_update(db, pid, "analysis", status="done", detail=f"{len(ok)}/{len(ids)} analyzed")
    return ok


async def _run_questions(db: AsyncIOMotorDatabase, pipeline: dict, ok: list[dict]) -> list[dict]:
    pid = pipeline["_id"]
    counts = pipeline["question_config"]["counts"]
    total_q = sum(counts.values())
    await step_update(db, pid, "questions", status="running", progress={"done": 0, "total": total_q})
    await log_event(db, pid, "questions", f"Generating {total_q} questions {counts}")
    questions = await question_agent.generate_questions(pipeline["jd_text"], [c["analysis"] for c in ok], counts)
    await step_update(db, pid, "questions", status="done", progress={"done": len(questions), "total": total_q},
                      detail=f"{len(questions)} questions validated")
    await log_event(db, pid, "questions", f"{len(questions)} questions ready")
    return questions


async def _run_assessment(db: AsyncIOMotorDatabase, pipeline: dict, ok: list[dict], questions: list[dict]) -> None:
    pid = pipeline["_id"]
    await step_update(db, pid, "assessment", status="running", progress={"done": 0, "total": 1})
    built = await assessment_agent.build_assessment(
        db, hiring_jd_id=pipeline["hiring_jd_id"], user_id=pipeline["created_by"], jd_title=pipeline["jd_title"],
        questions=questions, candidate_emails=[c["email"] for c in ok if c.get("email")],
        duration_minutes=pipeline["question_config"]["duration_minutes"],
    )
    await db[l1db.PIPELINES].update_one(
        {"_id": pid},
        {"$set": {"category_id": built["category_id"], "assessment_id": built["assessment_id"],
                  "share_id": built["share_id"], "share_link": built["share_link"]}},
    )
    await step_update(db, pid, "assessment", status="done", progress={"done": 1, "total": 1},
                      detail="Assessment and restricted link created")
    await log_event(db, pid, "assessment", "Assessment + restricted share link created")


def _invite_error(result: dict) -> dict | None:
    if not result["failed"]:
        return None
    return {"message": f"{result['failed']} invite email(s) failed",
            "detail": f"{mailer.last_error or 'SMTP error'} (server {settings.SMTP_HOST}:{settings.SMTP_PORT})"}


async def _run_invites(db: AsyncIOMotorDatabase, pid: ObjectId, ok: list[dict]) -> dict:
    n_email = sum(1 for c in ok if c.get("email"))
    await step_update(db, pid, "invites", status="running", progress={"done": 0, "total": n_email})
    await log_event(db, pid, "invites", f"Emailing {n_email} candidate(s)")
    result = await send_invites(db, str(pid))
    await step_update(db, pid, "invites", status="failed" if result["failed"] else "done",
                      progress={"done": result["invited"], "total": n_email},
                      detail=f"{result['invited']} invited, {result['failed']} failed", error=_invite_error(result))
    await log_event(db, pid, "invites", f"{result['invited']} invited, {result['failed']} failed",
                    "error" if result["failed"] else "info")
    await log_event(db, pid, "invites", "Pipeline complete. Exam and scoring run automatically after candidates submit.")
    return result


async def _final_status(db: AsyncIOMotorDatabase, pid: ObjectId, failed_invites: int) -> None:
    attention = await db[l1db.PIPELINE_CANDIDATES].count_documents(
        {"pipeline_id": pid, "status": {"$in": ["failed", "needs_email"]}})
    status = "done_with_errors" if attention or failed_invites else "done"
    await db[l1db.PIPELINES].update_one({"_id": pid}, {"$set": {"status": status}})


async def run_pipeline(db: AsyncIOMotorDatabase, pipeline_id: str) -> None:
    """Background entry point. Never raises; failures are stored on the step and pipeline."""
    pid = ObjectId(pipeline_id)
    current = "intake"
    keys = [s["key"] for s in STEP_CATALOG]
    try:
        pipeline = await db[l1db.PIPELINES].find_one({"_id": pid})
        cands = await db[l1db.PIPELINE_CANDIDATES].find({"pipeline_id": pid}).to_list(None)
        sem = asyncio.Semaphore(settings.LEVEL1_CONCURRENCY)
        parsed = await _run_intake(db, pid, sem, cands)
        current = "analysis"
        ok = await _run_analysis(db, pid, sem, pipeline["jd_text"], parsed)
        current = "questions"
        questions = await _run_questions(db, pipeline, ok)
        current = "assessment"
        await _run_assessment(db, pipeline, ok, questions)
        current = "invites"
        result = await _run_invites(db, pid, ok)
        await _final_status(db, pid, result["failed"])
    except StepFailureError as exc:
        await _fail(db, pid, exc.step, exc.message, exc.detail, keys)
    except Exception as exc:
        log.exception("Level 1 pipeline %s failed", pipeline_id)
        detail = getattr(exc, "detail", None)
        await _fail(db, pid, current, str(detail or exc)[:500] or type(exc).__name__, type(exc).__name__, keys)


async def _fail(db: AsyncIOMotorDatabase, pid: ObjectId, step: str, message: str, detail: str, keys: list[str]) -> None:
    await step_update(db, pid, step, status="failed", error={"message": message, "detail": detail})
    for k in keys[keys.index(step) + 1:]:
        await step_update(db, pid, k, status="skipped")
    full = f"{message} {detail}".strip()
    await log_event(db, pid, step, full, "error")
    await db[l1db.PIPELINES].update_one(
        {"_id": pid}, {"$set": {"status": "failed", "error": full[:600], "failed_step": step, "updated_at": utcnow()}})


async def start_run(*, hiring_jd_id: str, jd_title: str, jd_text: str, candidates: list[dict], created_by: str) -> str:
    """Insert the pipeline + candidate docs, launch the run in the background, return the pipeline id."""
    if not candidates:
        raise HTTPException(422, "At least one candidate is required")
    db = l1db.get_db()
    now = utcnow()
    pipeline = {
        "hiring_jd_id": hiring_jd_id,
        "jd_title": jd_title.strip(),
        "jd_text": jd_text.strip(),
        "status": "queued",
        "question_config": {"counts": dict(settings.LEVEL1_QUESTION_COUNTS), "duration_minutes": settings.LEVEL1_EXAM_MINUTES},
        "category_id": None, "assessment_id": None, "share_id": None, "share_link": None,
        "error": None,
        "steps": _new_steps(len(candidates)),
        "events": [],
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    pid = (await db[l1db.PIPELINES].insert_one(pipeline)).inserted_id
    await _insert_candidates(db, pid, candidates)
    task = asyncio.create_task(run_pipeline(db, str(pid)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return str(pid)


async def get_run(pipeline_id: str) -> dict:
    """Return the run with steps, events and candidates (profile text hidden)."""
    db = l1db.get_db()
    pipeline = await db[l1db.PIPELINES].find_one({"_id": oid(pipeline_id, "pipeline id")}, {"jd_text": 0})
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    cands = await db[l1db.PIPELINE_CANDIDATES].find({"pipeline_id": pipeline["_id"]}, _HIDDEN).to_list(None)
    out = serialize_doc(pipeline)
    out.setdefault("events", [])
    out["candidates"] = [serialize_doc(c) for c in cands]
    return out


async def find_run_for_jd(hiring_jd_id: str) -> dict | None:
    """Return the latest Level 1 run (serialized, without JD text) for a hiring JD."""
    db = l1db.get_db()
    doc = await db[l1db.PIPELINES].find_one({"hiring_jd_id": hiring_jd_id}, {"jd_text": 0}, sort=[("created_at", -1)])
    return serialize_doc(doc) if doc else None


async def _refresh_after_invites(db: AsyncIOMotorDatabase, pid: ObjectId, result: dict) -> None:
    col = db[l1db.PIPELINE_CANDIDATES]
    sent = await col.count_documents({"pipeline_id": pid, "invite_status": "sent"})
    total = await col.count_documents({"pipeline_id": pid, "email": {"$ne": None}})
    failed = await col.count_documents({"pipeline_id": pid, "invite_status": "failed"})
    error = {"message": f"{failed} invite email(s) failed", "detail": mailer.last_error or "SMTP error"} if failed else None
    await step_update(db, pid, "invites", status="failed" if failed else "done",
                      progress={"done": sent, "total": total}, detail=f"{sent} invited, {failed} failed", error=error)
    await _final_status(db, pid, failed)
    await log_event(db, pid, "invites", f"Resend: {result['invited']} sent, {result['failed']} failed")


async def resend_invites(pipeline_id: str) -> dict:
    """Send pending invites (fresh access keys) and refresh the invites step and run status."""
    db = l1db.get_db()
    pid = oid(pipeline_id, "pipeline id")
    if not await db[l1db.PIPELINES].find_one({"_id": pid}, {"_id": 1}):
        raise HTTPException(404, "Pipeline not found")
    result = await send_invites(db, pipeline_id)
    await _refresh_after_invites(db, pid, result)
    return result


async def add_candidates(pipeline_id: str, candidates: list[dict]) -> dict:
    """Analyze + invite late candidates against the run's existing assessment."""
    db = l1db.get_db()
    pid = oid(pipeline_id, "pipeline id")
    pipeline = await db[l1db.PIPELINES].find_one({"_id": pid})
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    if not pipeline.get("assessment_id") or not pipeline.get("share_id"):
        raise ValueError("The Level 1 run has no assessment yet (still running or failed); retry later")
    existing = {c["user_id"] async for c in db[l1db.PIPELINE_CANDIDATES].find({"pipeline_id": pid}, {"user_id": 1})}
    fresh = [c for c in candidates if str(c["user_id"]) not in existing]
    if not fresh:
        return {"invited": 0, "failed": 0}
    docs = await _insert_candidates(db, pid, fresh)
    sem = asyncio.Semaphore(settings.LEVEL1_CONCURRENCY)
    await asyncio.gather(*(_intake_candidate(db, sem, pid, d) for d in docs))
    ids = [d["_id"] for d in docs]
    cache: dict[str, dict] = {}
    await asyncio.gather(*(_analyze_candidate(db, sem, pipeline["jd_text"], pid, i, cache) for i in ids))
    ready = await db[l1db.PIPELINE_CANDIDATES].find({"_id": {"$in": ids}, "email": {"$ne": None}, "analysis": {"$ne": None}}).to_list(None)
    await db[l1db.SHARES].update_one({"_id": ObjectId(pipeline["share_id"])},
                                     {"$addToSet": {"restricted_emails": {"$each": [c["email"] for c in ready]}}})
    result = await send_invites(db, pipeline_id, [c["_id"] for c in ready])
    await _refresh_after_invites(db, pid, result)
    return result
