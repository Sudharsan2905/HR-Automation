"""Hiring orchestration: sourced profiles -> Level 1 exam -> automatic Level 2 -> final report."""

import asyncio
import html
from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
from pymongo.errors import DuplicateKeyError

from app._core.settings import settings
from app.components.auth import service as auth_service
from app.components.auth.models import User
from app.components.evaluation.models import EvaluationResult
from app.components.hiring.models import HiringCandidate, HiringEvent, HiringFlow
from app.components.interview.models import Interview
from app.components.jd_interview import service as jd_service
from app.components.jd_interview.models import JdInterview
from app.components.question_set.service import finalize_question_set
from app.components.sourcing import service as sourcing_service
from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun
from app.components.utils.email_client import get_email_client
from app.components.utils.logger import log

_locks: dict[str, asyncio.Lock] = {}
_batching: set[str] = set()  # JDs whose run-finish is selecting profiles; hooks wait for the batch


def _lock(jd_id: str) -> asyncio.Lock:
    return _locks.setdefault(jd_id, asyncio.Lock())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def log_event(jd_id: str, stage: str, message: str, level: str = "info") -> None:
    """Append to the JD's activity feed."""
    await HiringEvent(sourcing_jd_id=jd_id, stage=stage, level=level, message=message).insert()


def profile_text(p: SourcedProfile) -> str:
    """Flatten a sourced profile into text the Level 1 / Level 2 agents can read."""
    lines = [p.name, p.headline, f"{p.current_title} at {p.current_company}".strip(" at"),
             f"Location: {p.location}", f"Experience: {p.total_experience}",
             f"Skills: {', '.join(p.skills)}"]
    for exp in p.experiences:
        lines.append(" | ".join(str(v) for v in exp.values() if v))
    for edu in p.education:
        lines.append(" | ".join(str(v) for v in edu.values() if v))
    return "\n".join(x for x in lines if x and x.strip())[: settings.RESUME_MAX_CHARS]


async def _owner(jd: SourcingJd) -> User:
    owner = await User.get(jd.created_by)
    if not owner:
        raise HTTPException(404, "JD owner not found")
    return owner


async def _flow(jd_id: str) -> HiringFlow:
    flow = await HiringFlow.find_one(HiringFlow.sourcing_jd_id == jd_id)
    if flow:
        return flow
    try:
        flow = HiringFlow(sourcing_jd_id=jd_id)
        await flow.insert()
    except DuplicateKeyError:  # created concurrently by another request
        flow = await HiringFlow.find_one(HiringFlow.sourcing_jd_id == jd_id)
    return flow


async def ensure_candidate(p: SourcedProfile) -> HiringCandidate | None:
    """Create the hiring row for a promoted profile (idempotent)."""
    if not p.candidate_user_id or not p.email:
        return None
    hc = await HiringCandidate.find_one(
        HiringCandidate.sourcing_jd_id == p.sourcing_jd_id, HiringCandidate.profile_id == str(p.id)
    )
    if hc:
        return hc
    hc = HiringCandidate(sourcing_jd_id=p.sourcing_jd_id, profile_id=str(p.id),
                         user_id=p.candidate_user_id, name=p.name, email=p.email.lower())
    await hc.insert()
    return hc


# --- Sourcing hooks -----------------------------------------------------------

async def on_run_finished(run_id: str) -> None:
    """After a sourcing run: auto-select shortlisted profiles that have contact details."""
    try:
        run = await SourcingRun.get(run_id)
        jd = await SourcingJd.get(run.sourcing_jd_id) if run else None
        if not run or not jd or run.status != "done":
            return
        jd_id = str(jd.id)
        await log_event(jd_id, "sourcing", f"Run {run.run_no} finished: {run.profiles_shortlisted} shortlisted")
        if settings.HIRING_AUTO_SELECT:
            await _auto_select(jd, jd_id)
        await sync_level1(jd_id)
    except Exception as e:
        log.error("Hiring on_run_finished failed: %s", e, exc_info=True)


async def _auto_select(jd: SourcingJd, jd_id: str) -> None:
    owner = await _owner(jd)
    shortlisted = await SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jd_id, SourcedProfile.status == "shortlisted"
    ).to_list()
    _batching.add(jd_id)
    try:
        for p in (x for x in shortlisted if x.email):
            await sourcing_service.set_status(str(p.id), "selected", "Auto-selected by the hiring flow", owner)
    finally:
        _batching.discard(jd_id)
    need_contact = sum(1 for x in shortlisted if not x.email)
    if need_contact:
        await log_event(jd_id, "sourcing", f"{need_contact} shortlisted profile(s) need a contact reveal before Level 1 can be sent", "warn")


async def on_profile_promoted(p: SourcedProfile) -> None:
    """A selected profile became a SkillMate candidate: queue it for Level 1."""
    hc = await ensure_candidate(p)
    if hc and p.sourcing_jd_id not in _batching:
        asyncio.create_task(sync_level1(p.sourcing_jd_id))


# --- Level 1 ------------------------------------------------------------------

async def sync_level1(jd_id: str) -> dict | None:
    """Start the Level 1 run for waiting candidates, or add them to the existing run."""
    from app.components.level1 import pipeline_service

    async with _lock(jd_id):
        jd = await SourcingJd.get(jd_id)
        if not jd:
            return None
        waiting = await HiringCandidate.find(
            HiringCandidate.sourcing_jd_id == jd_id, HiringCandidate.level1_status == "not_started"
        ).to_list()
        if not waiting:
            return None
        cands = []
        for hc in waiting:
            p = await SourcedProfile.get(hc.profile_id)
            cands.append({"user_id": hc.user_id, "name": hc.name, "email": hc.email,
                          "profile_text": profile_text(p) if p else hc.name, "description": ""})
        flow = await _flow(jd_id)
        try:
            if not flow.level1_pipeline_id:
                flow.level1_pipeline_id = await pipeline_service.start_run(
                    hiring_jd_id=jd_id, jd_title=jd.title, jd_text=jd.jd_text,
                    candidates=cands, created_by=jd.created_by)
                flow.updated_at = _now()
                await flow.save()
                await log_event(jd_id, "level1", f"Level 1 started for {len(cands)} candidate(s)")
                result: dict = {"pipeline_id": flow.level1_pipeline_id}
            else:
                result = await pipeline_service.add_candidates(flow.level1_pipeline_id, cands)
                await log_event(jd_id, "level1", f"{len(cands)} more candidate(s) added to Level 1")
        except Exception as e:
            await log_event(jd_id, "level1", f"Could not start Level 1: {str(e)[:200]}", "error")
            log.error("Level 1 sync failed for %s: %s", jd_id, e, exc_info=True)
            return None
        for hc in waiting:
            hc.level1_status = "invited"
            hc.updated_at = _now()
            await hc.save()
        return result


async def start_level1(jd_id: str) -> dict:
    """Manual start/retry for every selected profile that already has contact details."""
    jd = await SourcingJd.get(jd_id)
    if not jd:
        raise HTTPException(404, "JD not found")
    selected = await SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jd_id, SourcedProfile.status == "selected"
    ).to_list()
    for p in selected:
        await ensure_candidate(p)
    result = await sync_level1(jd_id)
    if not result:
        raise HTTPException(400, "No candidates are waiting for Level 1 (select profiles that have an email first)")
    return result


def _final_outcome(sub: dict) -> tuple[float, bool]:
    pct = float(sub.get("percentage") or 0)
    return pct, sub.get("status") == "completed" and pct > settings.LEVEL1_PASS_PERCENT


async def on_level1_final(submission_id: str) -> None:
    """Called once every Level 1 answer is evaluated: expire the key, email, maybe promote."""
    try:
        from app.components.level1.db import get_db
        from app.components.level1.report_service import build_report_html

        db = get_db()
        sub = await db.l1_submissions.find_one({"_id": ObjectId(submission_id)})
        aid = sub["assessment_id"] if sub else None
        # pipelines store the id as text, submissions as ObjectId: accept both
        pipeline = await db.l1_pipelines.find_one({"assessment_id": {"$in": [aid, str(aid)]}}) if sub else None
        if not sub or not pipeline:
            return
        jd_id = pipeline["hiring_jd_id"]
        hc = await HiringCandidate.find_one(
            HiringCandidate.sourcing_jd_id == jd_id, HiringCandidate.user_id == str(sub["candidate_id"])
        )
        if not hc:
            return
        if hc.level1_report_sent and (hc.level1_status != "passed" or hc.level2_interview_id):
            return  # already fully handled; a passed candidate without Level 2 is retried
        already_notified = hc.level1_report_sent
        pct, passed = _final_outcome(sub)
        hc.level1_submission_id = submission_id
        hc.level1_percentage = pct
        hc.level1_status = "passed" if passed else ("terminated" if sub.get("status") != "completed" else "failed")
        hc.updated_at = _now()
        await hc.save()
        user = await User.get(hc.user_id)
        if user:
            await auth_service.expire_level1_key(user)
        jd = await SourcingJd.get(jd_id)
        await log_event(jd_id, "level1", f"{hc.name} scored {pct:.1f}% - {'passed' if passed else 'not advanced'}",
                        "info" if passed else "warn")
        if not already_notified:
            await _email_level1_result(hc, jd.title if jd else "the role", pct, passed,
                                       build_report_html(jd.title if jd else "Assessment", hc.name, sub))
        if passed:
            await promote_to_level2(hc)
    except Exception as e:
        log.error("Hiring on_level1_final failed: %s", e, exc_info=True)


async def _email_level1_result(hc: HiringCandidate, title: str, pct: float, passed: bool, report_html: str) -> None:
    client = get_email_client()
    if passed:
        note = (f"Congratulations! You scored {pct:.1f}%, above the {settings.LEVEL1_PASS_PERCENT}% mark. "
                "Your Level 2 interview details will follow in a separate email.")
    else:
        note = (f"You scored {pct:.1f}%. The pass mark for the next round is above "
                f"{settings.LEVEL1_PASS_PERCENT}%, so we will not be moving forward this time.")
    body = f"<p>{html.escape(note)}</p>{report_html}"
    ok = True
    if client:
        ok = await client.send_html(hc.email, f"Your Level 1 result - {title}", body)
    else:
        log.info("[Email Mock] Level 1 result to %s", hc.email)
    hc.level1_report_sent = ok
    await hc.save()


async def recheck_level1(jd_id: str) -> dict:
    """Finalize exams that are fully evaluated but were never processed (e.g. after a restart)."""
    from app.components.level1.db import get_db

    flow = await _flow(jd_id)
    if not flow.level1_pipeline_id:
        return {"rechecked": 0}
    pipeline = await get_db().l1_pipelines.find_one({"_id": ObjectId(flow.level1_pipeline_id)})
    if not pipeline or not pipeline.get("assessment_id"):
        return {"rechecked": 0}
    aid = pipeline["assessment_id"]
    subs = await get_db().l1_submissions.find(
        {"assessment_id": {"$in": [aid, ObjectId(aid) if isinstance(aid, str) else aid]},
         "status": {"$in": ["completed", "terminated", "malpractice"]},
         "scoring_completed_at": {"$ne": None}}).to_list(None)
    for sub in subs:
        await on_level1_final(str(sub["_id"]))
    return {"rechecked": len(subs)}


# --- Level 2 ------------------------------------------------------------------

async def promote_to_level2(hc: HiringCandidate, manual: bool = False) -> dict:
    """Create the Level 2 voice interview from the JD + candidate profile and email the key."""
    async with _lock(f"l2:{hc.id}"):
        hc = await HiringCandidate.get(hc.id)
        if hc.level2_interview_id:
            return {"interview_id": hc.level2_interview_id}
        jd = await SourcingJd.get(hc.sourcing_jd_id)
        profile = await SourcedProfile.get(hc.profile_id)
        owner = await _owner(jd)
        background = BackgroundTasks()
        created = await jd_service.create_jd_interview(
            owner, background, title=f"{jd.title} - {hc.name}", role_title=jd.requirements.role_title or jd.title,
            jd_text=jd.jd_text, jd_file=None, resume_text=profile_text(profile) if profile else None,
            resume_file=None, difficulty="auto", num_questions=None)
        await background()  # generate the question set now
        record = await JdInterview.get(created["id"])
        if not record or record.generation_status != "done":
            err = (record.generation_error if record else None) or "Question generation failed"
            await log_event(hc.sourcing_jd_id, "level2", f"Level 2 for {hc.name} failed: {err}", "error")
            raise HTTPException(502, err)
        await finalize_question_set(record.question_set_id, str(owner.id), is_admin=True)
        due = _now() + timedelta(days=settings.LEVEL2_DUE_DAYS)
        assigned = await jd_service.assign(created["id"], hc.email, hc.name, due.isoformat(), owner)
        hc.level2_jd_interview_id = created["id"]
        hc.level2_interview_id = assigned["interview_id"]
        hc.level2_due_date = due
        hc.promoted_manually = manual
        hc.updated_at = _now()
        await hc.save()
        await log_event(hc.sourcing_jd_id, "level2",
                        f"Level 2 interview scheduled for {hc.name} (email: {assigned.get('email_status')})")
        return {"interview_id": assigned["interview_id"], "email_status": assigned.get("email_status")}


async def resend_level2_key(hc_id: str) -> dict:
    hc = await _get_hc(hc_id)
    if not hc.level2_interview_id:
        raise HTTPException(400, "Level 2 is not scheduled yet")
    user = await User.get(hc.user_id)
    key = await auth_service.issue_level2_key(user)
    client = get_email_client()
    link = settings.APP_URL.rstrip("/") + "/login"
    sent = bool(client) and await client.send_html(
        hc.email, f"Your Level 2 access key - {settings.APP_NAME}",
        f"<p>Hello {html.escape(hc.name)},</p><p>Log in at <a href=\"{link}\">{link}</a> with "
        f"your email and this access key: <b>{html.escape(key)}</b></p>")
    return {"sent": sent}


async def resend_level1(hc_id: str) -> dict:
    from app.components.level1 import pipeline_service

    hc = await _get_hc(hc_id)
    flow = await _flow(hc.sourcing_jd_id)
    if not flow.level1_pipeline_id:
        raise HTTPException(400, "Level 1 has not started")
    return {"sent": bool(await pipeline_service.resend_invites(flow.level1_pipeline_id))}


async def promote_manually(hc_id: str) -> dict:
    hc = await _get_hc(hc_id)
    return await promote_to_level2(hc, manual=True)


async def _get_hc(hc_id: str) -> HiringCandidate:
    hc = await HiringCandidate.get(hc_id)
    if not hc:
        raise HTTPException(404, "Candidate not found")
    return hc


# --- Read models --------------------------------------------------------------

def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


async def _level2_view(hc: HiringCandidate) -> dict:
    status, rec = "not_started", None
    if hc.level2_interview_id:
        interview = await Interview.get(hc.level2_interview_id)
        status = "scheduled"
        if interview and interview.is_live:
            status = "in_progress"
        elif interview and interview.status.value in ("completed", "partially_completed"):
            status = "completed"
            if await EvaluationResult.find_one(EvaluationResult.interview_id == hc.level2_interview_id):
                status = "report_ready"
        jd_int = await JdInterview.get(hc.level2_jd_interview_id) if hc.level2_jd_interview_id else None
        if jd_int and jd_int.report_id:
            from app.components.jd_interview.models import JdReport

            report = await JdReport.get(jd_int.report_id)
            rec = report.recommendation if report else None
    return {"status": status, "interview_id": hc.level2_interview_id, "jd_interview_id": hc.level2_jd_interview_id,
            "due_date": _iso(hc.level2_due_date), "recommendation": rec}


async def _candidate_view(hc: HiringCandidate, l1_by_user: dict[str, dict], assessment_id: str | None = None) -> dict:
    p = await SourcedProfile.get(hc.profile_id)
    user = await User.get(hc.user_id)
    run_c = l1_by_user.get(hc.user_id, {})
    status = hc.level1_status
    if status == "invited" and run_c.get("started"):
        status = "in_progress"
    if status == "invited" and run_c.get("evaluating"):
        status = "evaluating"
    l2 = await _level2_view(hc)
    return {
        "id": str(hc.id), "profile_id": hc.profile_id, "name": hc.name, "email": hc.email,
        "score": p.score if p else None,
        "level1": {"status": status, "percentage": hc.level1_percentage,
                   "submission_id": hc.level1_submission_id or run_c.get("submission_id"),
                   "assessment_id": assessment_id,
                   "key_expires_at": _iso(user.level1_key_expires_at) if user else None},
        "level2": l2,
        "final_report_sent": l2["status"] == "report_ready",
    }


async def _level1_run(jd_id: str) -> tuple[dict | None, dict[str, dict]]:
    """The Level 1 pipeline doc (steps/events) plus per-user exam progress."""
    flow = await _flow(jd_id)
    if not flow.level1_pipeline_id:
        return None, {}
    from app.components.level1 import pipeline_service
    from app.components.level1.db import get_db

    run = await pipeline_service.get_run(flow.level1_pipeline_id)
    by_user: dict[str, dict] = {}
    if run.get("assessment_id"):
        db = get_db()
        subs = await db.l1_submissions.find({"assessment_id": ObjectId(run["assessment_id"])}).to_list(None)
        for s in subs:
            by_user[str(s["candidate_id"])] = {
                "submission_id": str(s["_id"]), "started": True,
                "evaluating": s.get("status") == "completed" and not s.get("scoring_completed_at")}
    return run, by_user


def _stage(key: str, label: str, status: str, detail: str | None = None, error: str | None = None) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, "error": error}


def _stages(jd: SourcingJd, last_run: SourcingRun | None, run: dict | None, cands: list[dict]) -> list[dict]:
    jd_stage = _stage("jd", "JD analysis", {"done": "done", "failed": "failed"}.get(jd.analysis_status, "running"),
                      error=jd.analysis_error)
    if not last_run:
        sourcing = _stage("sourcing", "Naukri sourcing", "pending", "Click Source from Naukri")
    else:
        sourcing = _stage("sourcing", "Naukri sourcing",
                          {"done": "done", "failed": "failed"}.get(last_run.status, "running"),
                          f"{last_run.profiles_shortlisted} shortlisted", last_run.error)
    l1_status = "pending"
    if run:
        l1_status = {"done": "done", "done_with_errors": "done", "failed": "failed"}.get(run.get("status", ""), "running")
        if l1_status == "done" and any(c["level1"]["status"] in ("invited", "in_progress", "evaluating") for c in cands):
            l1_status = "waiting"
    l1 = _stage("level1", "Level 1 exam", l1_status, f"pass mark above {settings.LEVEL1_PASS_PERCENT}%", run.get("error") if run else None)
    sched = [c for c in cands if c["level2"]["status"] != "not_started"]
    l2_status = "pending"
    if sched:
        l2_status = "done" if all(c["level2"]["status"] in ("completed", "report_ready") for c in sched) else "waiting"
    l2 = _stage("level2", "Level 2 interview", l2_status, f"{len(sched)} scheduled")
    ready = [c for c in cands if c["final_report_sent"]]
    rep = _stage("report", "Final report", "done" if sched and len(ready) == len(sched) else "pending",
                 f"{len(ready)} sent")
    return [jd_stage, sourcing, l1, l2, rep]


async def get_flow(jd_id: str) -> dict:
    jd = await SourcingJd.get(jd_id)
    if not jd:
        raise HTTPException(404, "JD not found")
    run, l1_by_user = await _level1_run(jd_id)
    hcs = await HiringCandidate.find(HiringCandidate.sourcing_jd_id == jd_id).sort("+created_at").to_list()
    assessment_id = str(run["assessment_id"]) if run and run.get("assessment_id") else None
    cands = [await _candidate_view(hc, l1_by_user, assessment_id) for hc in hcs]
    last_run = await SourcingRun.find(SourcingRun.sourcing_jd_id == jd_id).sort("-created_at").first_or_none()
    events = await HiringEvent.find(HiringEvent.sourcing_jd_id == jd_id).sort("+ts").limit(300).to_list()
    return {
        "jd": {"id": jd_id, "title": jd.title, "analysis_status": jd.analysis_status},
        "settings": {"pass_percent": settings.LEVEL1_PASS_PERCENT},
        "stages": _stages(jd, last_run, run, cands),
        "level1_run": ({"pipeline_id": str(run.get("id") or run.get("_id")), "status": run.get("status"),
                        "assessment_id": assessment_id,
                        "steps": run.get("steps", []), "events": run.get("events", [])} if run else None),
        "candidates": cands,
        "events": [{"ts": e.ts.isoformat(), "stage": e.stage, "level": e.level, "message": e.message} for e in events],
    }


async def list_flows(user: User) -> list[dict]:
    query = SourcingJd.find_all() if user.role.value == "super_admin" else SourcingJd.find(SourcingJd.created_by == str(user.id))
    out = []
    for jd in await query.sort("-created_at").limit(200).to_list():
        jd_id = str(jd.id)
        hcs = await HiringCandidate.find(HiringCandidate.sourcing_jd_id == jd_id).to_list()
        l1_done = sum(1 for h in hcs if h.level1_status in ("passed", "failed", "terminated"))
        l2_done = sum(1 for h in hcs if h.level2_interview_id)
        stage = "level2" if l2_done else "level1" if hcs else "sourcing" if jd.analysis_status == "done" else "jd"
        out.append({"jd_id": jd_id, "title": jd.title, "created_at": jd.created_at.isoformat(),
                    "candidate_count": len(hcs), "stage_summary": {"level1_done": l1_done, "level2_done": l2_done},
                    "current_stage": stage})
    return out
