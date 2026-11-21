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


# -- the JD's experience range for LinkedIn candidates ----------------------------------------------------------------------

async def _scored(fake_llm, **card):
    user = await make_user()
    jd = await make_ready_jd(user)                       # experience range 3 to 6 years
    run_id = await _run(jd, user)
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-1"]))
    await service.receive_profiles(run_id, [li(1, **card)], user, BackgroundTasks(), scanned=1)
    await service.process_page(run_id)
    return await SourcedProfile.find_one(SourcedProfile.sourcing_jd_id == str(jd.id))


async def test_a_linkedin_candidate_whose_profile_shows_too_little_experience_is_rejected(fake_llm):
    p = await _scored(fake_llm, experience_years=1.5, total_experience="1 yrs 6 mos")
    assert p.score == 0 and p.score_breakdown["rejected_reason"] == "experience out of range"


async def test_but_not_when_only_part_of_the_history_was_visible(fake_llm):
    """A long profile lists only some positions: 1.5 visible years is a floor, so it can't make anyone too junior."""
    p = await _scored(fake_llm, experience_years=1.5, experience_is_lower_bound=True)
    assert p.score_breakdown["rejected_reason"] is None and p.score >= 60 and p.status == "shortlisted"


async def test_a_partial_history_can_still_prove_someone_too_senior(fake_llm):
    p = await _scored(fake_llm, experience_years=9, experience_is_lower_bound=True)
    assert p.score_breakdown["rejected_reason"] == "experience out of range"


async def test_a_candidate_inside_the_range_is_unaffected_and_unknown_experience_is_not_judged(fake_llm):
    assert (await _scored(fake_llm, experience_years=4.5)).score >= 60


def test_the_scorer_treats_a_floor_like_this():
    from app.components.sourcing.models import SkillSpec, SourcingRequirements
    from app.components.sourcing.schemas import LLMScreenedProfile, LLMSkillFinding
    from app.components.sourcing.scoring import compute_score
    req = SourcingRequirements(mandatory_skills=[SkillSpec(name="Python")], experience_min_years=3, experience_max_years=6)
    s = LLMScreenedProfile(source_link="l", mandatory=[LLMSkillFinding(skill="Python", match="present")])
    assert compute_score(s, 1.0, None, req)[1]["rejected_reason"] == "experience out of range"
    assert compute_score(s, 1.0, None, req, experience_is_floor=True)[1]["rejected_reason"] is None
    assert compute_score(s, 7.0, None, req, experience_is_floor=True)[1]["rejected_reason"] == "experience out of range"
    assert compute_score(s, None, None, req)[1]["rejected_reason"] is None


# -- what the extension read on every page is kept on the run ---------------------------------------------------------------

async def test_each_pages_record_is_kept_and_only_the_newest_are_retained(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=10,
                                   debug="contacts p1: cards=10 degrees=1st:10/2nd:0/3rd:0/?:0 asked=10 opened=10 readable=10 emails=0")
    await service.process_page(run_id)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=10, debug="contacts p2: cards=10 asked=10 readable=10 emails=0")
    run = await SourcingRun.get(run_id)
    assert run.debug.startswith("contacts p1:") and " | contacts p2:" in run.debug
    # a record that would push the total past the cap keeps the NEWEST text
    await service.process_page(run_id)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=1, debug="contacts p3: " + "a" * 900 + " END")
    run = await SourcingRun.get(run_id)
    assert len(run.debug) <= 1000 and run.debug.endswith("END")
    assert not run.debug.startswith("contacts p1:")                                       # the oldest was pushed out


async def test_a_page_without_a_record_leaves_the_run_record_alone(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _run(jd, user)
    await service.receive_profiles(run_id, [li(1)], user, BackgroundTasks())
    assert (await SourcingRun.get(run_id)).debug == ""


async def test_the_record_over_http_is_capped_and_shown_on_the_run():
    user = await make_user()
    jd = await make_ready_jd(user)
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        run = (await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})).json()["data"]["run"]
        assert (await c.post(f"/api/sourcing/runs/{run['id']}/profiles", json={"profiles": [], "scanned": 1, "debug": "d" * 1001})).status_code == 422
        r = await c.post(f"/api/sourcing/runs/{run['id']}/profiles", json={"profiles": [], "scanned": 3, "debug": "contacts p1: cards=3 readable=3 emails=0"})
        assert r.status_code == 202
        assert (await c.get(f"/api/sourcing/runs/{run['id']}")).json()["data"]["debug"] == "contacts p1: cards=3 readable=3 emails=0"
