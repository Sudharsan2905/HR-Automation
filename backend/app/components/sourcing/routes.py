from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile

from app.components.auth.dependencies import get_effective_user
from app.components.auth.models import User
from app.components.sourcing import service
from app.components.sourcing.models import SourcingRequirements, SourcingSearchPlan
from app.components.sourcing.schemas import ContactIn, ProfilesIn, RunFailIn, StartRunIn, StatusUpdateIn

router = APIRouter(prefix="/sourcing", tags=["Sourcing"])


@router.post("/jds")
async def create_jd(
    background_tasks: BackgroundTasks,
    title: str | None = Form(None),
    jd_text: str | None = Form(None),
    jd_file: UploadFile | None = File(None),
    user: User = Depends(get_effective_user),
):
    """Create a sourcing JD (text or PDF/DOCX); requirements and search plan are built in the background."""
    return await service.create_sourcing_jd(user, background_tasks, title=title, jd_text=jd_text, jd_file=jd_file)


@router.get("/jds")
async def list_jds(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                   user: User = Depends(get_effective_user)):
    return await service.list_jds(user, skip, limit)


@router.get("/jds/{jd_id}")
async def get_jd(jd_id: str, user: User = Depends(get_effective_user)):
    return await service.get_detail(jd_id, user)


@router.post("/jds/{jd_id}/reanalyze")
async def reanalyze(jd_id: str, background_tasks: BackgroundTasks, user: User = Depends(get_effective_user)):
    return await service.reanalyze(jd_id, user, background_tasks)


@router.put("/jds/{jd_id}/requirements")
async def update_requirements(jd_id: str, req: SourcingRequirements, background_tasks: BackgroundTasks,
                              user: User = Depends(get_effective_user)):
    return await service.update_requirements(jd_id, req, user, background_tasks)


@router.put("/jds/{jd_id}/search-plan")
async def update_search_plan(jd_id: str, plan: SourcingSearchPlan, user: User = Depends(get_effective_user)):
    return await service.update_search_plan(jd_id, plan, user)


@router.delete("/jds/{jd_id}")
async def delete_jd(jd_id: str, user: User = Depends(get_effective_user)):
    return await service.delete_jd(jd_id, user)


@router.post("/jds/{jd_id}/runs")
async def start_run(jd_id: str, background_tasks: BackgroundTasks, body: StartRunIn | None = None,
                    user: User = Depends(get_effective_user)):
    """Source candidates: serve from the pool (screening leftovers first), or start a page-by-page scrape run
    on `source` ("naukri" by default, or "linkedin")."""
    return await service.start_run(jd_id, user, background_tasks, source=body.source if body else "naukri")


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(get_effective_user)):
    return await service.get_run(run_id, user)


@router.post("/runs/{run_id}/profiles", status_code=202)
async def receive_profiles(run_id: str, body: ProfilesIn, background_tasks: BackgroundTasks,
                           user: User = Depends(get_effective_user)):
    """The extension posts one results page (ResDex or LinkedIn); screening runs in the background, then the
    run asks for the next page (next_action="next_page") or finishes."""
    return await service.receive_profiles(run_id, body.profiles, user, background_tasks, ended=body.ended,
                                          source_url=body.source_url, search_level=body.search_level, scanned=body.scanned)


@router.post("/runs/{run_id}/fail")
async def fail_run(run_id: str, body: RunFailIn, user: User = Depends(get_effective_user)):
    return await service.fail_run(run_id, body.reason, body.detail, user, debug=body.debug)


@router.get("/jds/{jd_id}/profiles")
async def list_profiles(jd_id: str, status: str | None = None, user: User = Depends(get_effective_user)):
    return await service.list_profiles(jd_id, user, status)


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str, user: User = Depends(get_effective_user)):
    """One candidate's complete data: work history, education, per-skill screening, status history."""
    return await service.get_profile(profile_id, user)


@router.post("/profiles/{profile_id}/status")
async def set_status(profile_id: str, body: StatusUpdateIn, user: User = Depends(get_effective_user)):
    return await service.set_status(profile_id, body.status, body.note, user)


@router.post("/profiles/{profile_id}/contact")
async def save_contact(profile_id: str, body: ContactIn, user: User = Depends(get_effective_user)):
    return await service.save_contact(profile_id, body.email, body.phone, user)
