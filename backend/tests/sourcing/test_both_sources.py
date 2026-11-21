"""One click can check both Naukri and LinkedIn.

The page runs Naukri, and when it finishes starts LinkedIn too. Two things in the backend make that work:
- `use_pool=False`: the second source must read its own site, not be answered from what the first one left in the pool;
- a source's run shortlists only its own people, so neither source fills its places with the other's.
And the same person on both sources is kept once."""

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app.components.auth.dependencies import get_effective_user
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile, SourcingRun
from app.components.sourcing.routes import router
from tests.sourcing.helpers import all_present_batch, make_ready_jd, make_user, scraped
from tests.sourcing.test_linkedin_source import batch, li


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def _pool_naukri(jd, n=5, score=90):
    for i in range(n):
        await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source="Naukri", source_link=f"https://resdex.naukri.com/p/{i}",
                             name=f"Naukri {i}", score=score, status="pool").insert()


async def _statuses(jd, source):
    rows = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id), SourcedProfile.source == source).to_list()
    return {p.name: p.status for p in rows}


# -- the second source reads its own site ----------------------------------------------------------------------------

async def test_by_default_a_click_is_served_from_the_pool_as_before():
    user = await make_user()
    jd = await make_ready_jd(user)
    await _pool_naukri(jd)
    res = await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin")
    assert res["mode"] == "pool"


async def test_use_pool_false_reads_the_site_even_when_matches_are_waiting():
    user = await make_user()
    jd = await make_ready_jd(user)
    await _pool_naukri(jd)
    res = await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin", use_pool=False)
    assert res["mode"] == "scrape" and res["source"] == "linkedin" and res["run"]["next_action"] == "next_page"
    assert all(v == "pool" for v in (await _statuses(jd, "Naukri")).values())      # nothing was taken from the pool


async def test_use_pool_false_also_skips_screening_leftovers():
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source="Naukri", source_link="https://x/1", name="Unscreened",
                         status="pool").insert()                                    # read earlier, never screened
    assert (await service.start_run(str(jd.id), user, BackgroundTasks(), source="naukri"))["mode"] == "pool"
    run = await SourcingRun.find_one(SourcingRun.sourcing_jd_id == str(jd.id))
    await service.fail_run(str(run.id), "cancelled", "", user)
    assert (await service.start_run(str(jd.id), user, BackgroundTasks(), source="naukri", use_pool=False))["mode"] == "scrape"


# -- each source fills its own places ----------------------------------------------------------------------------------

async def test_a_linkedin_run_never_shortlists_naukri_people_from_the_pool(fake_llm):
    """Five Naukri people scoring 90 sit in the pool. The LinkedIn run finds two matches. It must stay at two: before, the
    top-up would have filled the other three places with Naukri people, and LinkedIn would have added almost nothing."""
    user = await make_user()
    jd = await make_ready_jd(user)
    await _pool_naukri(jd)
    run_id = (await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin", use_pool=False))["run"]["id"]
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-1", "https://www.linkedin.com/in/li-2"]))
    await service.receive_profiles(run_id, [li(1), li(2)], user, BackgroundTasks(), scanned=2)
    await service.process_page(run_id)
    assert set((await _statuses(jd, "LinkedIn")).values()) == {"shortlisted"}
    assert all(v == "pool" for v in (await _statuses(jd, "Naukri")).values())
    assert (await SourcingRun.get(run_id)).profiles_shortlisted == 2


async def test_a_naukri_run_never_shortlists_linkedin_people_from_the_pool(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    for i in range(4):
        await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source="LinkedIn", source_link=f"https://www.linkedin.com/in/old-{i}",
                             name=f"Old Li {i}", score=95, email=f"old{i}@example.com", status="pool").insert()
    run_id = (await service.start_run(str(jd.id), user, BackgroundTasks(), source="naukri", use_pool=False))["run"]["id"]
    fake_llm.queue(all_present_batch([scraped(1).source_link]))
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    await service.process_page(run_id)
    assert (await _statuses(jd, "Naukri")) == {"Cand 1": "shortlisted"}
    assert all(v == "pool" for v in (await _statuses(jd, "LinkedIn")).values())


async def test_one_click_two_sources_each_adds_its_own(fake_llm):
    """The whole sequence the page runs: Naukri first, then LinkedIn without the pool."""
    user = await make_user()
    jd = await make_ready_jd(user)

    naukri_run = (await service.start_run(str(jd.id), user, BackgroundTasks(), source="naukri"))["run"]["id"]
    fake_llm.queue(all_present_batch([scraped(i).source_link for i in range(3)]))
    await service.receive_profiles(naukri_run, [scraped(i) for i in range(3)], user, BackgroundTasks(), ended=True)
    await service.process_page(naukri_run)
    assert (await SourcingRun.get(naukri_run)).status == "done"

    li_run = (await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin", use_pool=False))["run"]["id"]
    fake_llm.queue(batch([f"https://www.linkedin.com/in/li-{i}" for i in (1, 2)]))
    await service.receive_profiles(li_run, [li(1), li(2)], user, BackgroundTasks(), ended=True, scanned=2)
    await service.process_page(li_run)

    assert sorted((await _statuses(jd, "Naukri")).values()) == ["shortlisted"] * 3
    assert sorted((await _statuses(jd, "LinkedIn")).values()) == ["shortlisted"] * 2


# -- one copy of a person -------------------------------------------------------------------------------------------------

async def test_the_same_email_on_both_sources_is_kept_once_at_intake(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r0", source="Naukri", source_link="https://resdex.naukri.com/p/9", name="Asha K",
                         email="asha@example.com", score=70, status="shortlisted").insert()
    run_id = (await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin", use_pool=False))["run"]["id"]
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-2"]))
    out = await service.receive_profiles(run_id, [li(1, name="Asha Kumar", email="Asha@Example.com"), li(2)], user, BackgroundTasks(), scanned=2)
    assert out == {"accepted": 1, "duplicates": 1, "no_email": 0}
    assert sorted((await _statuses(jd, "LinkedIn")).keys()) == ["Li 2"]


async def test_selecting_one_copy_retires_the_other_undecided_copies():
    """Naukri's email is only revealed at Select, so the LinkedIn copy (email known) can already be shortlisted."""
    user = await make_user()
    jd = await make_ready_jd(user)
    jd_id = str(jd.id)
    naukri = SourcedProfile(sourcing_jd_id=jd_id, run_id="r1", source="Naukri", source_link="https://resdex.naukri.com/p/1", name="Asha K",
                            score=82, status="shortlisted")
    linkedin = SourcedProfile(sourcing_jd_id=jd_id, run_id="r2", source="LinkedIn", source_link="https://www.linkedin.com/in/asha",
                              name="Asha Kumar", email="asha@example.com", score=63, status="shortlisted")
    other = SourcedProfile(sourcing_jd_id=jd_id, run_id="r2", source="LinkedIn", source_link="https://www.linkedin.com/in/ravi",
                           name="Ravi S", email="ravi@example.com", score=64, status="shortlisted")
    await naukri.insert(); await linkedin.insert(); await other.insert()

    await service.set_status(str(naukri.id), "selected", "", user)
    await service.save_contact(str(naukri.id), "Asha@Example.com", "9000000001", user)      # the reveal gives the same email

    assert (await SourcedProfile.get(naukri.id)).status == "selected"
    dup = await SourcedProfile.get(linkedin.id)
    assert dup.status == "rejected"
    assert dup.status_history[-1].by == "system" and "Duplicate" in dup.status_history[-1].note and "Asha K (Naukri)" in dup.status_history[-1].note
    assert (await SourcedProfile.get(other.id)).status == "shortlisted"                       # a different person is untouched


async def test_a_copy_the_recruiter_already_selected_or_rejected_is_left_alone():
    user = await make_user()
    jd = await make_ready_jd(user)
    jd_id = str(jd.id)
    first = SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source="LinkedIn", source_link="https://www.linkedin.com/in/a", name="A",
                           email="same@example.com", status="selected")
    held = SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source="Naukri", source_link="https://resdex.naukri.com/p/2", name="A2",
                          email="same@example.com", status="on_hold")
    other_jd = await make_ready_jd(user)
    elsewhere = SourcedProfile(sourcing_jd_id=str(other_jd.id), run_id="r", source="Naukri", source_link="https://resdex.naukri.com/p/3", name="A3",
                               email="same@example.com", status="shortlisted")
    chosen = SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source="Naukri", source_link="https://resdex.naukri.com/p/4", name="A4",
                            email="same@example.com", status="shortlisted")
    for p in (first, held, elsewhere, chosen):
        await p.insert()
    await service.set_status(str(chosen.id), "selected", "", user)
    assert (await SourcedProfile.get(first.id)).status == "selected"            # already selected: not touched
    assert (await SourcedProfile.get(held.id)).status == "rejected"             # undecided (on hold): retired
    assert (await SourcedProfile.get(elsewhere.id)).status == "shortlisted"     # another JD: not touched


# -- HTTP contract ---------------------------------------------------------------------------------------------------------

async def test_the_run_endpoint_takes_use_pool():
    user = await make_user()
    jd = await make_ready_jd(user)
    await _pool_naukri(jd)
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin", "use_pool": False})
        assert r.status_code == 200 and r.json()["data"]["mode"] == "scrape"
        await c.post(f"/api/sourcing/runs/{r.json()['data']['run']['id']}/fail", json={"reason": "cancelled"})
        for body in ({"source": "linkedin"}, {"source": "linkedin", "use_pool": True}, {}):
            r = await c.post(f"/api/sourcing/jds/{jd.id}/runs", json=body)
            assert r.status_code == 200 and r.json()["data"]["mode"] == "pool", body
            break
        r = await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin", "use_pool": "maybe"})
        assert r.status_code == 422
