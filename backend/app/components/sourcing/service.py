"""Sourcing module: JD lifecycle, Source-from-Naukri runs, profile intake and selection."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from beanie.operators import In, NE
from fastapi import BackgroundTasks, HTTPException, UploadFile

from app._core.settings import settings
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.sourcing import agents
from app.components.sourcing.models import (
    SourcedProfile,
    SourcingJd,
    SourcingRequirements,
    SourcingRun,
    SourcingSearchPlan,
    StatusEvent,
)
from app.components.sourcing.schemas import ScrapedProfileIn
from app.components.sourcing.scoring import apply_source_rules, compute_score, related_notes
from app.components.utils.logger import log
from app.components.utils.resume_parser import parse_resume

MIN_JD_CHARS = 80
STATUSES = ("pool", "shortlisted", "selected", "rejected", "on_hold", "below_threshold")
ACTIVE_RUN_STATUSES = ("pending", "scraping", "screening")
SOURCES = ("naukri", "linkedin")


@dataclass(frozen=True)
class _SourceCfg:
    label: str            # stored on each profile ("Naukri" / "LinkedIn")
    pages_per_run: int    # most pages one click reads while looking for SOURCING_BATCH_SIZE matches
    prefetch_pages: int   # pages read into the pool once the batch is found
    max_page: int


def _source_cfg(source: str) -> _SourceCfg:
    if source == "linkedin":
        return _SourceCfg("LinkedIn", settings.SOURCING_LINKEDIN_PAGES_PER_RUN,
                          settings.SOURCING_LINKEDIN_PREFETCH_PAGES, settings.SOURCING_LINKEDIN_MAX_PAGE)
    return _SourceCfg("Naukri", settings.SOURCING_PAGES_PER_RUN, settings.SOURCING_PREFETCH_PAGES,
                      settings.SOURCING_MAX_PAGE)


def _next_page(jd: SourcingJd, source: str) -> int:
    return jd.linkedin_next_page if source == "linkedin" else jd.next_page


def _is_exhausted(jd: SourcingJd, source: str) -> bool:
    return jd.linkedin_exhausted if source == "linkedin" else jd.pool_exhausted


def _set_paging(jd: SourcingJd, source: str, *, next_page: int | None = None, exhausted: bool | None = None) -> None:
    if source == "linkedin":
        if next_page is not None:
            jd.linkedin_next_page = next_page
        if exhausted is not None:
            jd.linkedin_exhausted = exhausted
    else:
        if next_page is not None:
            jd.next_page = next_page
        if exhausted is not None:
            jd.pool_exhausted = exhausted


def _normalize_link(link: str, source: str) -> str:
    """One LinkedIn person = one link: drop the query string, fragment, trailing slash and host variants,
    so the same profile read twice (or via a different page) is recognised as already found."""
    link = (link or "").strip()
    if source != "linkedin" or not link:
        return link
    try:
        u = urlparse(link)
    except ValueError:
        return link
    host = (u.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return link
    path = u.path.rstrip("/")
    return f"https://www.linkedin.com{path}" if path else link


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Access checks (same rules as JD Analyze) ─────────────────────────────────

def _ensure_writer(user: User) -> None:
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Only the admin can do this")


def _ensure_reader(user: User) -> None:
    if user.role not in (Role.INTERVIEWER, Role.SUPER_ADMIN):
        raise HTTPException(403, "Insufficient permissions")


async def _get_owned(jd_id: str, user: User, *, write: bool) -> SourcingJd:
    try:
        jd = await SourcingJd.get(jd_id)
    except Exception:
        jd = None
    if not jd:
        raise HTTPException(404, "Sourcing JD not found")
    if write:
        _ensure_writer(user)
        if jd.created_by != str(user.id):
            raise HTTPException(403, "Not your sourcing JD")
    else:
        _ensure_reader(user)
        if user.role != Role.SUPER_ADMIN and jd.created_by != str(user.id):
            raise HTTPException(403, "Not your sourcing JD")
    return jd


async def _get_owned_run(run_id: str, user: User, *, write: bool) -> tuple[SourcingRun, SourcingJd]:
    try:
        run = await SourcingRun.get(run_id)
    except Exception:
        run = None
    if not run:
        raise HTTPException(404, "Sourcing run not found")
    jd = await _get_owned(run.sourcing_jd_id, user, write=write)
    return run, jd


async def _read_upload(upload: UploadFile) -> str:
    try:
        value = (await parse_resume(upload)).strip()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.warning("Sourcing JD parse failed: %s", e)
        raise HTTPException(400, "Could not read the JD file")
    if not value:
        raise HTTPException(400, "No text found in the JD file (scanned/image-only files are not supported)")
    return value


async def _read_jd_input(text: str | None, upload: UploadFile | None) -> str:
    """The JD text: a pasted JD wins; otherwise the uploaded PDF/DOCX is parsed.

    Pasted text too short to be a JD (a title, "full stack development") does not hide an uploaded file: the file is
    used instead. Without a file, a short paste is refused with the numbers, not a generic message."""
    pasted = (text or "").strip()
    has_file = upload is not None and bool(upload.filename)
    value = pasted if (len(pasted) >= MIN_JD_CHARS or not has_file) else await _read_upload(upload)
    if len(value) > settings.JD_MAX_CHARS:
        raise HTTPException(400, f"JD is too long ({len(value)} characters, max {settings.JD_MAX_CHARS})")
    if len(value) < MIN_JD_CHARS:
        if not value:
            raise HTTPException(400, "Please provide a job description (paste the text or upload a PDF/DOCX file)")
        where = "The job description in the file" if has_file else "The pasted job description"
        raise HTTPException(
            400, f"{where} is too short ({len(value)} characters; at least {MIN_JD_CHARS} are needed). "
                 "Paste the full job description or upload a PDF/DOCX that contains it.")
    return value


# ── Serialisation ────────────────────────────────────────────────────────────

def _run_out(run: SourcingRun) -> dict:
    return {
        "id": str(run.id), "run_no": run.run_no, "mode": run.mode, "source": run.source, "status": run.status,
        "error": run.error, "debug": run.debug,
        "pages_from": run.pages_from, "pages_to": run.pages_to, "pages_crawled": run.pages_crawled,
        "phase": run.phase, "next_action": run.next_action,
        "source_url": run.source_url, "profiles_received": run.profiles_received,
        "profiles_new": run.profiles_new, "profiles_shortlisted": run.profiles_shortlisted,
        "created_at": run.created_at, "finished_at": run.finished_at,
    }


def _profile_out(p: SourcedProfile, existing_owner: str | None = None) -> dict:
    return {
        "id": str(p.id), "run_id": p.run_id, "shortlisted_in_run_id": p.shortlisted_in_run_id,
        "source": p.source, "name": p.name, "headline": p.headline, "location": p.location,
        "current_company": p.current_company, "current_title": p.current_title,
        "experience_years": p.experience_years, "current_ctc_lacs": p.current_ctc_lacs, "skills": p.skills,
        "source_link": p.source_link, "email": p.email, "phone": p.phone,
        "score": p.score, "score_breakdown": p.score_breakdown, "match_reasons": p.match_reasons,
        "related_notes": p.related_notes, "status": p.status,
        "status_history": [e.model_dump() for e in p.status_history],
        "candidate_user_id": p.candidate_user_id, "existing_candidate_owner": existing_owner,
    }


async def _counts(jd_ids: list[str]) -> dict[str, dict[str, int]]:
    out = {jid: {s: 0 for s in STATUSES} for jid in jd_ids}
    if not jd_ids:
        return out
    pipeline = [{"$group": {"_id": {"jd": "$sourcing_jd_id", "status": "$status"}, "n": {"$sum": 1}}}]
    rows = await SourcedProfile.find(In(SourcedProfile.sourcing_jd_id, jd_ids)).aggregate(pipeline).to_list()
    for r in rows:
        jid, status = r["_id"]["jd"], r["_id"]["status"]
        if jid in out and status in out[jid]:
            out[jid][status] = r["n"]
    return out


def _summary(jd: SourcingJd, counts: dict[str, int]) -> dict:
    return {
        "id": str(jd.id), "title": jd.title, "role_title": jd.requirements.role_title,
        "analysis_status": jd.analysis_status, "analysis_error": jd.analysis_error,
        "counts": counts, "created_at": jd.created_at,
    }


async def _active_run(jd_id: str) -> SourcingRun | None:
    return await SourcingRun.find_one(
        SourcingRun.sourcing_jd_id == jd_id, In(SourcingRun.status, list(ACTIVE_RUN_STATUSES)),
    )


async def _detail(jd: SourcingJd) -> dict:
    jid = str(jd.id)
    await _expire_stale_runs(jid)
    counts = (await _counts([jid]))[jid]
    pool_ready = await SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jid, SourcedProfile.status == "pool", NE(SourcedProfile.score, None),
    ).count()
    runs = await SourcingRun.find(SourcingRun.sourcing_jd_id == jid).sort(-SourcingRun.run_no).to_list()
    active = await _active_run(jid)
    return {
        **_summary(jd, counts),
        "jd_text": jd.jd_text,
        "requirements": jd.requirements.model_dump(),
        "search_plan": jd.search_plan.model_dump(),
        "next_page": jd.next_page,
        "pool_exhausted": jd.pool_exhausted,
        "linkedin_next_page": jd.linkedin_next_page,
        "linkedin_exhausted": jd.linkedin_exhausted,
        "linkedin_search_level": jd.linkedin_search_level,
        "pool_count": pool_ready,
        "active_run": _run_out(active) if active else None,
        "runs": [_run_out(r) for r in runs],
    }


# ── JD lifecycle ─────────────────────────────────────────────────────────────

async def create_sourcing_jd(user: User, background_tasks: BackgroundTasks, *, title: str | None,
                             jd_text: str | None, jd_file: UploadFile | None) -> dict:
    _ensure_writer(user)
    text = await _read_jd_input(jd_text, jd_file)
    jd = SourcingJd(
        created_by=str(user.id),
        title=(title or "").strip() or "Sourcing JD",
        jd_text=text,
        jd_filename=jd_file.filename if jd_file and jd_file.filename else None,
    )
    await jd.insert()
    background_tasks.add_task(run_analysis, str(jd.id))
    log.info("Sourcing JD created: %s", jd.id)
    return _summary(jd, {s: 0 for s in STATUSES})


async def run_analysis(jd_id: str) -> None:
    """Background: Agent 1 (requirements) then Agent 2 (search plan)."""
    jd = await SourcingJd.get(jd_id)
    if not jd:
        return
    try:
        req = await agents.analyze_jd(jd.jd_text)
        plan = await agents.build_search_plan(req)
        jd.requirements = req
        jd.search_plan = plan
        jd.requirements_version += 1
        jd.next_page = 1
        jd.pool_exhausted = False
        jd.linkedin_next_page = 1
        jd.linkedin_exhausted = False
        jd.linkedin_search_level = 0
        jd.analysis_status = "done"
        jd.analysis_error = None
        jd.updated_at = _now()
        await jd.save()
    except Exception as e:
        log.error("Sourcing JD analysis failed for %s: %s", jd_id, e, exc_info=True)
        jd.analysis_status = "failed"
        jd.analysis_error = str(e)[:300] or "JD analysis failed. Please try again."
        jd.updated_at = _now()
        await jd.save()
        return
    if jd.requirements_version > 1:
        await rescreen_pool(jd_id)


async def reanalyze(jd_id: str, user: User, background_tasks: BackgroundTasks) -> dict:
    jd = await _get_owned(jd_id, user, write=True)
    await _expire_stale_runs(jd_id)
    if await _active_run(jd_id):
        raise HTTPException(409, "Wait for the running sourcing run to finish")
    jd.analysis_status = "generating"
    jd.analysis_error = None
    jd.updated_at = _now()
    await jd.save()
    background_tasks.add_task(run_analysis, jd_id)
    return {"message": "Re-analysis started"}


async def update_requirements(jd_id: str, req: SourcingRequirements, user: User,
                              background_tasks: BackgroundTasks) -> dict:
    jd = await _get_owned(jd_id, user, write=True)
    jd.requirements = req
    jd.requirements_version += 1
    jd.updated_at = _now()
    await jd.save()
    background_tasks.add_task(rescreen_pool, jd_id)
    return await _detail(jd)


async def update_search_plan(jd_id: str, plan: SourcingSearchPlan, user: User) -> dict:
    jd = await _get_owned(jd_id, user, write=True)
    jd.search_plan = plan
    jd.next_page = 1
    jd.pool_exhausted = False
    jd.linkedin_next_page = 1
    jd.linkedin_exhausted = False
    jd.linkedin_search_level = 0
    jd.updated_at = _now()
    await jd.save()
    return await _detail(jd)


async def list_jds(user: User, skip: int, limit: int) -> dict:
    _ensure_reader(user)
    query = SourcingJd.find_all() if user.role == Role.SUPER_ADMIN else SourcingJd.find(SourcingJd.created_by == str(user.id))
    total = await query.count()
    jds = await query.sort(-SourcingJd.created_at).skip(skip).limit(limit).to_list()
    counts = await _counts([str(j.id) for j in jds])
    return {"total": total, "items": [_summary(j, counts[str(j.id)]) for j in jds]}


async def get_detail(jd_id: str, user: User) -> dict:
    jd = await _get_owned(jd_id, user, write=False)
    return await _detail(jd)


async def delete_jd(jd_id: str, user: User) -> dict:
    jd = await _get_owned(jd_id, user, write=True)
    await _expire_stale_runs(jd_id)
    if await _active_run(jd_id):
        raise HTTPException(409, "Wait for the running sourcing run to finish")
    await SourcedProfile.find(SourcedProfile.sourcing_jd_id == jd_id).delete()
    await SourcingRun.find(SourcingRun.sourcing_jd_id == jd_id).delete()
    await jd.delete()
    return {"message": "Sourcing JD deleted"}


# ── Screening ────────────────────────────────────────────────────────────────

async def _screen_and_score(jd: SourcingJd, profiles: list[SourcedProfile]) -> None:
    """Screen with Agent 3, score in code, and move each profile to pool / below_threshold."""
    if not profiles:
        return
    results = await agents.screen_profiles(jd.requirements, profiles)
    for p in profiles:
        s = results.get(p.source_link)
        if s is None:
            p.status = "below_threshold"
            p.score = 0
            p.score_breakdown = {"rejected_reason": "not screened", "total": 0}
            p.match_reasons = ["Could not be screened"]
            p.related_notes = []
            p.screening = None
        else:
            s = apply_source_rules(s, p.source)
            score, breakdown = compute_score(s, p.experience_years, p.current_ctc_lacs, jd.requirements)
            p.screening = s.model_dump()
            p.score = score
            p.score_breakdown = breakdown
            p.match_reasons = s.match_reasons
            p.related_notes = related_notes(s)
            p.status = "pool" if score >= settings.SOURCING_MIN_SCORE else "below_threshold"
        p.screened_with_version = jd.requirements_version
        p.updated_at = _now()
        await p.save()


async def rescreen_pool(jd_id: str) -> None:
    """Re-score profiles not yet shown (pool / below_threshold) against the current requirements."""
    jd = await SourcingJd.get(jd_id)
    if not jd:
        return
    profiles = await SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jd_id, In(SourcedProfile.status, ["pool", "below_threshold"]),
    ).to_list()
    try:
        await _screen_and_score(jd, profiles)
    except Exception as e:
        log.error("Pool re-screen failed for %s: %s", jd_id, e, exc_info=True)


# ── Runs ─────────────────────────────────────────────────────────────────────
# A scrape run goes page by page: the extension posts one ResDex page, SkillMate screens it
# and shortlists from the pool, then either asks for the next page (next_action="next_page")
# or finishes. Phase "hunting" looks for SOURCING_BATCH_SIZE matches over at most
# SOURCING_PAGES_PER_RUN pages; once found, phase "prefetch" reads SOURCING_PREFETCH_PAGES more
# pages straight into the pool so the next click needs no ResDex at all.

async def _touch(run: SourcingRun) -> None:
    run.updated_at = _now()
    await run.save()


async def _expire_stale_runs(jd_id: str) -> None:
    cutoff = _now() - timedelta(minutes=settings.SOURCING_RUN_TIMEOUT_MINUTES)
    for run in await SourcingRun.find(
        SourcingRun.sourcing_jd_id == jd_id, In(SourcingRun.status, list(ACTIVE_RUN_STATUSES)),
    ).to_list():
        if _aware(run.updated_at or run.created_at) < cutoff:
            run.status = "failed"
            run.error = "timed out"
            run.next_action = None
            run.finished_at = _now()
            await _touch(run)


async def _shortlist_from_pool(jd_id: str, run_id: str, limit: int | None = None) -> int:
    limit = settings.SOURCING_BATCH_SIZE if limit is None else limit
    if limit <= 0:
        return 0
    best = await SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jd_id,
        SourcedProfile.status == "pool",
        NE(SourcedProfile.score, None),
    ).sort(-SourcedProfile.score).limit(limit).to_list()
    for p in best:
        p.status = "shortlisted"
        p.shortlisted_in_run_id = run_id
        p.status_history.append(StatusEvent(status="shortlisted", by="system"))
        p.updated_at = _now()
        await p.save()
    return len(best)


def _unscored_pool(jd_id: str, *extra):
    return SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jd_id,
        SourcedProfile.status == "pool",
        SourcedProfile.score == None,  # noqa: E711 — Beanie query, not a Python comparison
        *extra,
    )


async def start_run(jd_id: str, user: User, background_tasks: BackgroundTasks, source: str = "naukri") -> dict:
    """One "Source candidates" click. Screened matches already in the pool are served first whatever the
    source; only a run that must read a site names its source ("naukri" or "linkedin")."""
    if source not in SOURCES:
        raise HTTPException(400, f"Unknown source: {source}")
    jd = await _get_owned(jd_id, user, write=True)
    if jd.analysis_status != "done":
        raise HTTPException(400, "The JD is still being analyzed")
    await _expire_stale_runs(jd_id)
    if await _active_run(jd_id):
        raise HTTPException(409, "A sourcing run is already in progress")

    run_no = await SourcingRun.find(SourcingRun.sourcing_jd_id == jd_id).count() + 1
    pool_ready = await SourcedProfile.find(
        SourcedProfile.sourcing_jd_id == jd_id, SourcedProfile.status == "pool", NE(SourcedProfile.score, None),
    ).count()

    # 1. Already-screened matches waiting in the pool.
    if pool_ready:
        run = SourcingRun(sourcing_jd_id=jd_id, run_no=run_no, clicked_by=str(user.id), mode="pool", status="done",
                          source=source)
        await run.insert()
        run.profiles_shortlisted = await _shortlist_from_pool(jd_id, str(run.id))
        run.finished_at = _now()
        await _touch(run)
        _notify_hiring_run_done(str(run.id))
        return {"run": _run_out(run), "mode": "pool"}

    # 2. Profiles read earlier but not screened yet: screen those before opening ResDex.
    if await _unscored_pool(jd_id).count():
        run = SourcingRun(sourcing_jd_id=jd_id, run_no=run_no, clicked_by=str(user.id), mode="pool",
                          status="screening", source=source, updated_at=_now())
        await run.insert()
        background_tasks.add_task(process_pool_run, str(run.id))
        return {"run": _run_out(run), "mode": "pool"}

    # 3. Read the chosen site, page by page.
    cfg = _source_cfg(source)
    if _is_exhausted(jd, source):
        raise HTTPException(
            409, f"No more matches on {cfg.label} for this search. Edit the keywords or switch between primary and narrowed.")
    page_from = _next_page(jd, source)
    page_to = min(page_from + cfg.pages_per_run + cfg.prefetch_pages - 1, cfg.max_page)
    plan = jd.search_plan
    run = SourcingRun(
        sourcing_jd_id=jd_id, run_no=run_no, clicked_by=str(user.id), mode="scrape", status="pending", source=source,
        keywords_used=plan.narrowed_keywords if plan.use_narrowed else plan.primary_keywords,
        pages_from=page_from, pages_to=page_to, pages_crawled=0, next_action="next_page", updated_at=_now(),
    )
    await run.insert()
    out = {"run": _run_out(run), "mode": "scrape", "source": source, "search_plan": plan.model_dump(),
           "page_from": page_from, "page_to": page_to}
    if source == "linkedin":
        out["search_level"] = jd.linkedin_search_level
    return out


async def get_run(run_id: str, user: User) -> dict:
    run, _ = await _get_owned_run(run_id, user, write=False)
    return _run_out(run)


def _current_role(experiences: list[dict]) -> tuple[str, str]:
    if not experiences:
        return "", ""
    cur = next((e for e in experiences if isinstance(e, dict) and e.get("is_current")), experiences[0])
    if not isinstance(cur, dict):
        return "", ""
    return str(cur.get("company") or ""), str(cur.get("title") or "")


async def receive_profiles(run_id: str, profiles: list[ScrapedProfileIn], user: User,
                           background_tasks: BackgroundTasks, *, ended: bool = False,
                           source_url: str = "", search_level: int | None = None) -> dict:
    """One results page from an extension. Screening runs in the background.

    A person is stored once per JD: by profile link and, when the page already shows an email, by email too,
    so the same person found on Naukri and on LinkedIn is not screened (or emailed) twice."""
    run, jd = await _get_owned_run(run_id, user, write=True)
    if run.mode != "scrape" or run.status not in ("pending", "scraping") or run.next_action != "next_page":
        raise HTTPException(409, "This run is not waiting for a page")
    run.status = "screening"
    run.next_action = None
    run.profiles_received += len(profiles)
    if profiles:
        run.pages_crawled = (run.pages_crawled or 0) + 1
    run.results_ended = ended
    if source_url:
        run.source_url = source_url[:500]
    await _touch(run)
    if run.source == "linkedin" and search_level is not None and jd.linkedin_search_level != search_level:
        # The extension had to broaden the search to find anyone: later runs keep paging through that same search.
        jd.linkedin_search_level = search_level
        jd.updated_at = _now()
        await jd.save()

    jd_id = str(jd.id)
    cfg = _source_cfg(run.source)
    known = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == jd_id).to_list()
    existing = {p.source_link for p in known}
    existing_emails = {p.email.lower() for p in known if p.email}
    inserted = 0
    duplicates = 0
    for sp in profiles:
        link = _normalize_link(sp.source_link, run.source)
        email = (sp.email or "").strip().lower()
        if not link or link in existing:
            continue
        if email and email in existing_emails:
            duplicates += 1  # already found (maybe on the other source): keep the first copy only
            continue
        existing.add(link)
        if email:
            existing_emails.add(email)
        company, title = _current_role(sp.experiences)
        await SourcedProfile(
            sourcing_jd_id=jd_id, run_id=run_id, source=cfg.label, source_link=link,
            name=sp.name.strip() or "Unknown", snippet=sp.snippet,
            headline=sp.headline, location=sp.location, current_company=company, current_title=title,
            skills=sp.skills, experiences=sp.experiences, education=sp.education,
            total_experience=sp.total_experience, experience_years=sp.experience_years,
            current_ctc=sp.current_ctc, current_ctc_lacs=sp.current_ctc_lacs,
            email=email, phone=(sp.phone or "").strip(),
            raw=sp.model_dump(), status="pool",
        ).insert()
        inserted += 1

    run.profiles_new += inserted
    await _touch(run)
    background_tasks.add_task(process_page, run_id)
    return {"accepted": inserted, "duplicates": duplicates}


async def _finish(run: SourcingRun, status: str, error: str | None = None) -> None:
    """Save the outcome of a screening step unless the run was closed meanwhile (cancel, timeout)."""
    current = await SourcingRun.get(run.id)
    if current and current.status != "screening":
        return
    run.status = status
    run.error = error
    if status != "scraping":
        run.next_action = None
        run.finished_at = _now()
    await _touch(run)
    if status == "done":
        _notify_hiring_run_done(str(run.id))


def _notify_hiring_run_done(run_id: str) -> None:
    """Hand a finished run to the hiring flow without blocking sourcing."""
    from app.components.hiring.service import on_run_finished

    asyncio.create_task(on_run_finished(run_id))


async def process_page(run_id: str) -> None:
    """Background: screen the page just received, shortlist, then ask for another page or finish."""
    run = await SourcingRun.get(run_id)
    if not run or run.status != "screening":
        return
    jd = await SourcingJd.get(run.sourcing_jd_id)
    if not jd:
        return
    jd_id = str(jd.id)
    cfg = _source_cfg(run.source)
    try:
        new = await _unscored_pool(jd_id, SourcedProfile.run_id == run_id).to_list()
        await _screen_and_score(jd, new)

        if run.phase == "hunting":
            run.profiles_shortlisted += await _shortlist_from_pool(
                jd_id, run_id, settings.SOURCING_BATCH_SIZE - run.profiles_shortlisted)
            if run.profiles_shortlisted >= settings.SOURCING_BATCH_SIZE:
                run.phase = "prefetch"
                run.prefetch_left = cfg.prefetch_pages
        else:
            run.prefetch_left -= 1

        crawled = run.pages_crawled or 0
        next_page = (run.pages_from or 1) + crawled
        _set_paging(jd, run.source, next_page=next_page)
        if run.results_ended or next_page > cfg.max_page:
            _set_paging(jd, run.source, exhausted=True)
        jd.updated_at = _now()
        await jd.save()

        last_page_was_empty = crawled == 0 or run.profiles_received == 0
        more = (
            not _is_exhausted(jd, run.source)
            and not last_page_was_empty
            and next_page <= (run.pages_to or 0)
            and (
                (run.phase == "hunting" and crawled < cfg.pages_per_run)
                or (run.phase == "prefetch" and run.prefetch_left > 0)
            )
        )
        if more:
            run.next_action = "next_page"
            await _finish(run, "scraping")
        else:
            await _finish(run, "done")
    except Exception as e:
        log.error("Sourcing run %s failed: %s", run_id, e, exc_info=True)
        await _finish(run, "failed", str(e)[:300] or "Screening failed")


async def process_pool_run(run_id: str) -> None:
    """Background: screen leftover unscored pool profiles a page-sized group at a time; stop at 5."""
    run = await SourcingRun.get(run_id)
    if not run or run.status != "screening":
        return
    jd = await SourcingJd.get(run.sourcing_jd_id)
    if not jd:
        return
    jd_id = str(jd.id)
    group = max(1, settings.SOURCING_SCREEN_CHUNK * settings.SOURCING_SCREEN_CONCURRENCY)
    try:
        while run.profiles_shortlisted < settings.SOURCING_BATCH_SIZE:
            todo = await _unscored_pool(jd_id).sort(+SourcedProfile.id).limit(group).to_list()
            if not todo:
                break
            await _screen_and_score(jd, todo)
            run.profiles_shortlisted += await _shortlist_from_pool(
                jd_id, run_id, settings.SOURCING_BATCH_SIZE - run.profiles_shortlisted)
            run.profiles_received += len(todo)
            current = await SourcingRun.get(run_id)
            if current and current.status != "screening":
                return  # cancelled or timed out meanwhile
            await _touch(run)
        await _finish(run, "done")
    except Exception as e:
        log.error("Sourcing pool run %s failed: %s", run_id, e, exc_info=True)
        await _finish(run, "failed", str(e)[:300] or "Screening failed")


async def fail_run(run_id: str, reason: str, detail: str, user: User, debug: str = "") -> dict:
    run, _ = await _get_owned_run(run_id, user, write=True)
    if run.status in ("failed", "cancelled"):
        return _run_out(run)  # the extension and the page both report a failure: the first one wins, quietly
    if run.status not in ACTIVE_RUN_STATUSES:
        raise HTTPException(409, "This run has already finished")
    # Screening is SkillMate's own work; only the recruiter's Cancel may stop it.
    if run.status == "screening" and reason != "cancelled":
        raise HTTPException(409, "This run already received its profiles")
    run.status = "cancelled" if reason == "cancelled" else "failed"
    run.error = f"{reason}: {detail}" if detail else reason
    run.debug = (debug or "")[:1000]
    run.next_action = None
    run.finished_at = _now()
    await _touch(run)
    return _run_out(run)


async def list_profiles(jd_id: str, user: User, status: str | None) -> list[dict]:
    await _get_owned(jd_id, user, write=False)
    query = SourcedProfile.find(SourcedProfile.sourcing_jd_id == jd_id)
    if status:
        query = query.find(SourcedProfile.status == status)
    profiles = await query.sort(-SourcedProfile.score).to_list()
    return [_profile_out(p, await _owner_name(p, user)) for p in profiles]


# ── Selection → SkillMate candidate ──────────────────────────────────────────

STAFF_EMAIL_ERROR = "This email belongs to a panel member or admin and cannot be used as a candidate"
SELECTABLE_FROM = ("pool", "shortlisted", "selected", "rejected", "on_hold")


async def _get_owned_profile(profile_id: str, user: User, *, write: bool = True) -> SourcedProfile:
    try:
        p = await SourcedProfile.get(profile_id)
    except Exception:
        p = None
    if not p:
        raise HTTPException(404, "Profile not found")
    await _get_owned(p.sourcing_jd_id, user, write=write)
    return p


async def get_profile(profile_id: str, user: User) -> dict:
    """One candidate's complete data for the detail view."""
    p = await _get_owned_profile(profile_id, user, write=False)
    jd = await SourcingJd.get(p.sourcing_jd_id)
    screening = p.screening or {}

    ids = {e.by for e in p.status_history if e.by and e.by != "system"}
    names: dict[str, str] = {}
    for uid in ids:
        try:
            u = await User.get(uid)
        except Exception:
            u = None
        names[uid] = (u.full_name or u.email) if u else "Unknown user"

    out = _profile_out(p, await _owner_name(p, user))
    out.update({
        "jd_title": jd.title if jd else "",
        "total_experience": p.total_experience,
        "current_ctc": p.current_ctc,
        "experiences": p.experiences,
        "education": p.education,
        "mandatory_findings": screening.get("mandatory") or [],
        "preferred_findings": screening.get("preferred") or [],
        "screening_flags": {k: bool(screening.get(k)) for k in (
            "target_company_match", "avoid_company_match", "location_match", "seniority_match", "relevant_projects")},
        "contact_revealed_at": p.contact_revealed_at,
        "created_at": p.created_at,
        "status_history": [
            {**e.model_dump(), "by_name": "SkillMate" if e.by == "system" else names.get(e.by, "Unknown user")}
            for e in p.status_history
        ],
    })
    return out


async def _owner_name(p: SourcedProfile, user: User) -> str | None:
    """Name of the recruiter who owns the linked candidate, when it isn't the current recruiter."""
    if not p.candidate_user_id:
        return None
    try:
        cand = await User.get(p.candidate_user_id)
    except Exception:
        return None
    if not cand or not cand.created_by or cand.created_by == str(user.id):
        return None
    try:
        owner = await User.get(cand.created_by)
    except Exception:
        owner = None
    return (owner.full_name or owner.email) if owner else cand.created_by


async def _promote(p: SourcedProfile, user: User) -> str | None:
    """Create (or link) the SkillMate candidate for a selected profile. Returns an error message or None."""
    from app.components.auth.schemas import CandidateLinkRequest
    from app.components.auth.service import link_candidate

    clash = await User.find_one(User.email == p.email, User.role != Role.CANDIDATE)
    if clash:
        return STAFF_EMAIL_ERROR
    created = await link_candidate(CandidateLinkRequest(email=p.email, full_name=p.name), str(user.id))
    p.candidate_user_id = created["candidate_id"]
    p.updated_at = _now()
    await p.save()
    from app.components.hiring.service import on_profile_promoted

    try:
        await on_profile_promoted(p)
    except Exception as e:  # the hiring flow must never break profile selection
        log.error("Hiring hook failed for profile %s: %s", p.id, e, exc_info=True)
    return None


async def set_status(profile_id: str, status: str, note: str, user: User) -> dict:
    p = await _get_owned_profile(profile_id, user)
    if p.status not in SELECTABLE_FROM:
        raise HTTPException(400, f"Cannot change a {p.status} profile")
    p.status = status
    p.status_history.append(StatusEvent(status=status, by=str(user.id), note=(note or "").strip()))
    p.updated_at = _now()
    await p.save()
    needs_contact = False
    error = None
    if status == "selected" and not p.candidate_user_id:
        if p.email:
            error = await _promote(p, user)
        else:
            needs_contact = True
    return {"needs_contact": needs_contact, "candidate_error": error,
            "profile": _profile_out(p, await _owner_name(p, user))}


async def save_contact(profile_id: str, email: str | None, phone: str | None, user: User) -> dict:
    p = await _get_owned_profile(profile_id, user)
    if email and email.strip():
        p.email = email.strip().lower()
    if phone and phone.strip():
        p.phone = phone.strip()
    p.contact_revealed_at = _now()
    p.updated_at = _now()
    await p.save()
    error = None
    if p.status == "selected" and p.email and not p.candidate_user_id:
        error = await _promote(p, user)
    return {"profile": _profile_out(p, await _owner_name(p, user)), "candidate_error": error}
