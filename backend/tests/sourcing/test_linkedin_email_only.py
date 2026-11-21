"""LinkedIn candidates are only taken with an email.

LinkedIn cards never show one: the extension opens each candidate's contact dialog and sends only the people it got an
email for. The backend refuses anyone without one as well, keeps a page nobody shared an email on counted, and never
auto-invites these candidates (the recruiter's Select does)."""

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app._core.settings import settings
from app.components.auth.dependencies import get_effective_user
from app.components.hiring import service as hiring
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun
from app.components.sourcing.routes import router
from tests.sourcing.helpers import make_ready_jd, make_user, scraped
from tests.sourcing.test_linkedin_source import batch, li


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def _run(jd, user, source="linkedin"):
    return (await service.start_run(str(jd.id), user, BackgroundTasks(), source=source))["run"]["id"]


async def test_a_linkedin_profile_without_an_email_is_refused(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-1"]))
    out = await service.receive_profiles(
        run_id, [li(1), li(2, email=""), li(3, email="not-an-email")], user, BackgroundTasks(), scanned=6)
    assert out == {"accepted": 1, "duplicates": 0, "no_email": 2}
    stored = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id)).to_list()
    assert [p.email for p in stored] == ["li1@example.com"]
    run = await SourcingRun.get(run_id)
    assert (run.profiles_received, run.profiles_scanned) == (3, 6)


async def test_a_page_where_nobody_shared_an_email_still_counts_and_the_run_moves_on(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    out = await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=10)
    assert out["accepted"] == 0
    await service.process_page(run_id)
    run = await SourcingRun.get(run_id)
    assert run.pages_crawled == 1 and run.profiles_scanned == 10
    assert (run.status, run.next_action) == ("scraping", "next_page")          # keeps looking: it was not the end
    assert (await SourcingJd.get(jd.id)).linkedin_next_page == 2
    assert (await SourcingJd.get(jd.id)).linkedin_exhausted is False


async def test_a_truly_empty_page_is_still_the_end_of_the_results(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), ended=True, scanned=0)
    await service.process_page(run_id)
    assert (await SourcingRun.get(run_id)).status == "done"
    assert (await SourcingJd.get(jd.id)).linkedin_exhausted is True


async def test_pages_of_people_nobody_emailed_end_the_run_at_the_page_limit(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    for _ in range(settings.SOURCING_LINKEDIN_PAGES_PER_RUN):
        await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=10)
        await service.process_page(run_id)
    run = await SourcingRun.get(run_id)
    assert run.status == "done" and run.profiles_shortlisted == 0
    assert run.profiles_scanned == 10 * settings.SOURCING_LINKEDIN_PAGES_PER_RUN


async def test_naukri_still_takes_profiles_without_an_email(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user, "naukri")
    out = await service.receive_profiles(run_id, [scraped(1), scraped(2)], user, BackgroundTasks())
    assert out["accepted"] == 2 and out["no_email"] == 0


async def test_an_older_extension_that_sends_no_emails_gets_nothing_in_instead_of_unmailable_candidates(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    out = await service.receive_profiles(run_id, [li(i, email="") for i in range(4)], user, BackgroundTasks())
    assert out["accepted"] == 0 and out["no_email"] == 4


# -- no auto-invite: the recruiter's Select is the trigger for LinkedIn candidates ---------------------

async def test_linkedin_candidates_with_an_email_are_not_auto_selected(monkeypatch):
    admin = await make_user("admin@x.com")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    for i, (src, email) in enumerate([("LinkedIn", "li@x.com"), ("Naukri", "nk@x.com"), ("Naukri", "")]):
        await SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source=src, source_link=f"https://x/{i}", name=f"P{i}",
                             email=email, status="shortlisted").insert()
    selected = []

    async def fake_set_status(pid, status, note, user):
        selected.append((await SourcedProfile.get(pid)).name)

    monkeypatch.setattr(hiring.sourcing_service, "set_status", fake_set_status)
    await hiring._auto_select(jd, jd_id)
    assert selected == ["P1"]                                            # only the Naukri profile that has an email
    from app.components.hiring.models import HiringEvent
    events = [e.message for e in await HiringEvent.find(HiringEvent.sourcing_jd_id == jd_id).to_list()]
    assert any("LinkedIn candidate" in m and "wait for your Select" in m for m in events)


async def test_the_switch_can_bring_auto_select_back_for_linkedin(monkeypatch):
    monkeypatch.setattr(settings, "HIRING_AUTO_SELECT_LINKEDIN", True)
    admin = await make_user("admin@x.com")
    jd = await make_ready_jd(admin)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source="LinkedIn", source_link="https://x/1", name="P",
                         email="li@x.com", status="shortlisted").insert()
    selected = []

    async def fake_set_status(pid, status, note, user):
        selected.append(pid)

    monkeypatch.setattr(hiring.sourcing_service, "set_status", fake_set_status)
    await hiring._auto_select(jd, str(jd.id))
    assert len(selected) == 1


def test_defaults():
    assert settings.HIRING_AUTO_SELECT_LINKEDIN is False and settings.HIRING_AUTO_SELECT is True


# -- HTTP contract ---------------------------------------------------------------------------------------

async def test_the_page_endpoint_takes_scanned_and_reports_the_run_counts():
    user = await make_user()
    jd = await make_ready_jd(user)
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        run = (await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})).json()["data"]["run"]
        r = await c.post(f"/api/sourcing/runs/{run['id']}/profiles", json={"profiles": [], "scanned": 7})
        assert r.status_code == 202 and r.json()["data"] == {"accepted": 0, "duplicates": 0, "no_email": 0}
        assert (await c.get(f"/api/sourcing/runs/{run['id']}")).json()["data"]["profiles_scanned"] == 7
        r = await c.post(f"/api/sourcing/runs/{run['id']}/profiles", json={"profiles": [], "scanned": -1})
        assert r.status_code == 422
