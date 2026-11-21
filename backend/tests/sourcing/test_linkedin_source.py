"""LinkedIn as a second candidate source: its own paging, link/email dedupe against Naukri,
and the screening rule for LinkedIn cards ("unverified", never "absent")."""

import pytest
from fastapi import BackgroundTasks, HTTPException

from app._core.settings import settings
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun
from app.components.sourcing.schemas import (
    LLMScreenBatch,
    LLMScreenedProfile,
    LLMSkillFinding,
    ScrapedProfileIn,
)
from app.components.sourcing.scoring import apply_source_rules, related_notes

from tests.sourcing.helpers import make_ready_jd, make_user, scraped


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


def li(i: int, **kw) -> ScrapedProfileIn:
    data = dict(name=f"Li {i}", source_link=f"https://www.linkedin.com/in/li-{i}/?miniProfileUrn=urn%3Ali%3A{i}",
                headline="Python developer", snippet="Skills: Python, Django", email=f"li{i}@example.com",
                experiences=[{"company": f"Co{i}", "title": "Dev", "is_current": True}])
    data.update(kw)
    return ScrapedProfileIn(**data)


def batch(links, *, python="present", django="present") -> LLMScreenBatch:
    return LLMScreenBatch(profiles=[
        LLMScreenedProfile(
            source_link=link,
            mandatory=[LLMSkillFinding(skill="Python", match=python, strength="basic"),
                       LLMSkillFinding(skill="Django", match=django, strength="basic")],
            match_reasons=["card"],
        )
        for link in links
    ])


async def _run(jd, user, source):
    res = await service.start_run(str(jd.id), user, BackgroundTasks(), source=source)
    assert res["mode"] == "scrape"
    return res


# ── starting a run ───────────────────────────────────────────────────────────────

async def test_linkedin_run_uses_its_own_page_window_and_labels_the_run():
    user = await make_user()
    jd = await make_ready_jd(user)
    res = await _run(jd, user, "linkedin")
    assert res["source"] == "linkedin" and res["run"]["source"] == "linkedin"
    assert (res["page_from"], res["page_to"]) == (
        1, settings.SOURCING_LINKEDIN_PAGES_PER_RUN + settings.SOURCING_LINKEDIN_PREFETCH_PAGES)


async def test_unknown_source_is_refused():
    user = await make_user()
    jd = await make_ready_jd(user)
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks(), source="indeed")
    assert e.value.status_code == 400


async def test_naukri_exhausted_does_not_block_linkedin_and_vice_versa():
    user = await make_user()
    jd = await make_ready_jd(user, pool_exhausted=True, next_page=7)
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks(), source="naukri")
    assert e.value.status_code == 409 and "Naukri" in e.value.detail
    res = await _run(jd, user, "linkedin")           # LinkedIn still starts at its own page 1
    assert res["page_from"] == 1


async def test_linkedin_exhausted_message_names_linkedin():
    user = await make_user()
    jd = await make_ready_jd(user, linkedin_exhausted=True)
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin")
    assert e.value.status_code == 409 and "LinkedIn" in e.value.detail


async def test_pool_is_served_first_whatever_the_source():
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source_link="https://x/1", name="P", score=80,
                         status="pool").insert()
    res = await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin")
    assert res["mode"] == "pool" and res["run"]["profiles_shortlisted"] == 1


# ── a LinkedIn page arrives ───────────────────────────────────────────────────────

async def test_linkedin_page_is_stored_as_linkedin_with_a_clean_link(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    out = await service.receive_profiles(run_id, [li(1), li(2)], user, BackgroundTasks())
    assert out["accepted"] == 2
    profiles = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id)).to_list()
    assert {p.source for p in profiles} == {"LinkedIn"}
    assert {p.source_link for p in profiles} == {"https://www.linkedin.com/in/li-1", "https://www.linkedin.com/in/li-2"}
    assert all(p.snippet == "Skills: Python, Django" for p in profiles)


async def test_same_linkedin_person_with_a_different_url_form_is_stored_once(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    out = await service.receive_profiles(
        run_id, [li(1), li(1, source_link="https://linkedin.com/in/li-1/")], user, BackgroundTasks())
    assert out["accepted"] == 1


async def test_a_person_already_found_by_email_on_naukri_is_not_added_again_from_linkedin(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r0", source="Naukri", source_link="https://resdex/1",
                         name="Asha", email="asha@mail.com", status="rejected", score=0).insert()
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    out = await service.receive_profiles(
        run_id, [li(1, name="Asha K", email="ASHA@mail.com"), li(2)], user, BackgroundTasks())
    assert out == {"accepted": 1, "duplicates": 1, "no_email": 0}
    names = {p.name for p in await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id)).to_list()}
    assert names == {"Asha", "Li 2"}


async def test_naukri_run_still_stores_naukri_profiles_unchanged(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "naukri"))["run"]["id"]
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    p = await SourcedProfile.find_one(SourcedProfile.sourcing_jd_id == str(jd.id))
    assert p.source == "Naukri" and p.source_link == "https://resdex.naukri.com/p/1"


# ── paging is kept per source ──────────────────────────────────────────────────────

async def test_linkedin_paging_does_not_move_the_naukri_page(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    fake_llm.queue(batch([li(1).source_link.split("?")[0].rstrip("/")]))
    await service.receive_profiles(run_id, [li(1)], user, BackgroundTasks())
    await service.process_page(run_id)
    fresh = await SourcingJd.get(jd.id)
    assert fresh.linkedin_next_page == 2 and fresh.next_page == 1
    assert fresh.linkedin_exhausted is False and fresh.pool_exhausted is False


async def test_linkedin_hunting_stops_after_its_page_limit(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    for n in range(settings.SOURCING_LINKEDIN_PAGES_PER_RUN):
        fake_llm.queue(batch([f"https://www.linkedin.com/in/li-{100 + n}"], python="absent"))
        await service.receive_profiles(run_id, [li(100 + n)], user, BackgroundTasks())
        await service.process_page(run_id)
    run = await SourcingRun.get(run_id)
    assert run.status == "done"
    assert (await SourcingJd.get(jd.id)).linkedin_next_page == settings.SOURCING_LINKEDIN_PAGES_PER_RUN + 1


async def test_end_of_linkedin_results_marks_only_linkedin_exhausted(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-1"]))
    await service.receive_profiles(run_id, [li(1)], user, BackgroundTasks(), ended=True)
    await service.process_page(run_id)
    fresh = await SourcingJd.get(jd.id)
    assert fresh.linkedin_exhausted is True and fresh.pool_exhausted is False


async def test_new_search_plan_restarts_paging_on_both_sources():
    user = await make_user()
    jd = await make_ready_jd(user, next_page=4, pool_exhausted=True, linkedin_next_page=3, linkedin_exhausted=True)
    out = await service.update_search_plan(str(jd.id), jd.search_plan, user)
    assert (out["next_page"], out["pool_exhausted"]) == (1, False)
    assert (out["linkedin_next_page"], out["linkedin_exhausted"]) == (1, False)


# ── screening a LinkedIn card ─────────────────────────────────────────────────────

async def test_linkedin_card_missing_a_skill_is_unverified_not_rejected(fake_llm):
    """The model says "absent" for Django; for LinkedIn that becomes "unverified": still scored, with a note."""
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-1"], django="absent"))
    await service.receive_profiles(run_id, [li(1)], user, BackgroundTasks())
    await service.process_page(run_id)
    p = await SourcedProfile.find_one(SourcedProfile.sourcing_jd_id == str(jd.id))
    assert p.score == 60 and p.status == "shortlisted"
    assert p.related_notes == ["Django not shown on the LinkedIn card — verify"]


async def test_naukri_profile_missing_a_skill_is_still_rejected_even_if_the_model_says_unverified(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "naukri"))["run"]["id"]
    fake_llm.queue(batch(["https://resdex.naukri.com/p/1"], django="unverified"))
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    await service.process_page(run_id)
    p = await SourcedProfile.find_one(SourcedProfile.sourcing_jd_id == str(jd.id))
    assert p.score == 0 and p.score_breakdown["rejected_reason"] == "missing mandatory: Django"


def test_apply_source_rules_only_rewrites_the_missing_skill():
    s = LLMScreenedProfile(source_link="l", mandatory=[
        LLMSkillFinding(skill="Python", match="present"), LLMSkillFinding(skill="Django", match="absent"),
        LLMSkillFinding(skill="AWS", match="related", related_skill="GCP")])
    li_fixed = apply_source_rules(s, "LinkedIn")
    assert [f.match for f in li_fixed.mandatory] == ["present", "unverified", "related"]
    assert [f.match for f in apply_source_rules(li_fixed, "Naukri").mandatory] == ["present", "absent", "related"]
    assert related_notes(li_fixed)[-1] == "Django not shown on the LinkedIn card — verify"


def test_link_normalisation_only_touches_real_linkedin_hosts():
    n = service._normalize_link
    assert n("https://in.linkedin.com/in/asha/?x=1#y", "linkedin") == "https://www.linkedin.com/in/asha"
    assert n("https://linkedin.com/in/asha/", "linkedin") == "https://www.linkedin.com/in/asha"
    assert n("https://notlinkedin.com/in/asha/", "linkedin") == "https://notlinkedin.com/in/asha/"
    assert n("https://evil.example/?u=linkedin.com", "linkedin") == "https://evil.example/?u=linkedin.com"
    assert n("https://resdex.naukri.com/p/1/?x=1", "naukri") == "https://resdex.naukri.com/p/1/?x=1"   # Naukri links untouched
    assert n("", "linkedin") == ""


# ── the extension's search ladder: SkillMate remembers which step found people ──────────────────────

async def test_run_start_returns_the_remembered_search_step_for_linkedin_only():
    user = await make_user()
    jd = await make_ready_jd(user, linkedin_search_level=2)
    li_res = await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin")
    assert li_res["search_level"] == 2
    await service.fail_run(li_res["run"]["id"], "cancelled", "", user)
    naukri_res = await service.start_run(str(jd.id), user, BackgroundTasks(), source="naukri")
    assert "search_level" not in naukri_res


async def test_the_step_that_found_people_is_saved_with_the_first_page(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = (await _run(jd, user, "linkedin"))["run"]["id"]
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-1"]))
    await service.receive_profiles(run_id, [li(1)], user, BackgroundTasks(), search_level=3)
    assert (await SourcingJd.get(jd.id)).linkedin_search_level == 3
    # a page that doesn't say which step it came from leaves it alone
    await service.process_page(run_id)
    fake_llm.queue(batch(["https://www.linkedin.com/in/li-2"]))
    await service.receive_profiles(run_id, [li(2)], user, BackgroundTasks())
    assert (await SourcingJd.get(jd.id)).linkedin_search_level == 3


async def test_a_naukri_page_never_changes_the_linkedin_step(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user, linkedin_search_level=1)
    run_id = (await _run(jd, user, "naukri"))["run"]["id"]
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks(), search_level=4)
    assert (await SourcingJd.get(jd.id)).linkedin_search_level == 1


async def test_a_new_search_plan_or_analysis_starts_again_from_the_narrowest_step():
    user = await make_user()
    jd = await make_ready_jd(user, linkedin_search_level=3, linkedin_next_page=4)
    out = await service.update_search_plan(str(jd.id), jd.search_plan, user)
    assert out["linkedin_search_level"] == 0 and out["linkedin_next_page"] == 1


async def test_the_page_endpoint_accepts_and_validates_search_level():
    import httpx
    from fastapi import FastAPI
    from app._core.handler import register_exception_handlers
    from app._core.middleware import GlobalResponseMiddleware
    from app.components.auth.dependencies import get_effective_user
    from app.components.sourcing.routes import router
    from tests.sourcing.test_linkedin_routes import card

    user = await make_user()
    jd = await make_ready_jd(user)
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        run = (await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})).json()["data"]
        assert run["search_level"] == 0
        r = await c.post(f"/api/sourcing/runs/{run['run']['id']}/profiles", json={"profiles": [card(1)], "search_level": -1})
        assert r.status_code == 422
        r = await c.post(f"/api/sourcing/runs/{run['run']['id']}/profiles", json={"profiles": [card(1)], "search_level": 2})
        assert r.status_code == 202
        detail = (await c.get(f"/api/sourcing/jds/{jd.id}")).json()["data"]
        assert detail["linkedin_search_level"] == 2
