"""Regression tests for the final-review findings (Important #1-#5, #7)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.components.sourcing import service
from app.components.sourcing.models import SkillSpec, SourcedProfile, SourcingJd, SourcingRequirements, SourcingRun
from app.components.sourcing.schemas import LLMScreenedProfile, LLMSkillFinding
from app.components.sourcing.scoring import compute_score

from tests.sourcing.helpers import all_present_batch, make_ready_jd, make_user, scraped

STAFF_ERROR = "This email belongs to a panel member or admin and cannot be used as a candidate"


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def _scrape_run(jd, user):
    return (await service.start_run(str(jd.id), user, BackgroundTasks()))["run"]["id"]


# 1 — the staff-email refusal must reach the caller on select, too
async def test_select_with_staff_email_already_present_reports_error():
    user = await make_user()
    await make_user(email="panel@softsuave.com")
    jd = await make_ready_jd(user)
    p = SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source_link="https://x/1", name="P",
                       status="shortlisted", score=80, email="panel@softsuave.com")
    await p.insert()
    out = await service.set_status(str(p.id), "selected", "", user)
    assert out["candidate_error"] == STAFF_ERROR
    assert out["needs_contact"] is False
    assert out["profile"]["candidate_user_id"] is None


# 2 — a screening exception must not strand profiles in the pool unscored
async def test_screener_exception_does_not_strand_profiles(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    await service.receive_profiles(run_id, [scraped(1), scraped(2)], user, BackgroundTasks())
    # nothing queued → FakeLLM raises for the only chunk
    await service.process_page(run_id)
    rows = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id)).to_list()
    assert {p.status for p in rows} == {"below_threshold"}
    assert all(p.match_reasons == ["Could not be screened"] for p in rows)
    assert (await SourcingRun.get(run_id)).status == "scraping"  # nothing found — asks for the next page


async def test_pool_count_ignores_unscored_profiles():
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source_link="https://x/1", name="A", status="pool").insert()
    assert (await service.get_detail(str(jd.id), user))["pool_count"] == 0


# 3 — /fail must not hijack a run that already received its profiles
async def test_fail_during_screening_is_refused(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    with pytest.raises(HTTPException) as e:
        await service.fail_run(run_id, "error", "network", user)
    assert e.value.status_code == 409


# 4 — mandatory findings are matched to the requirements by name
def test_missing_mandatory_finding_is_not_a_pass():
    req = SourcingRequirements(mandatory_skills=[SkillSpec(name="Python"), SkillSpec(name="Django")])
    empty = LLMScreenedProfile(source_link="l", mandatory=[])
    score, b = compute_score(empty, 4, None, req)
    assert score == 0 and b["rejected_reason"] == "not screened: Python"
    partial = LLMScreenedProfile(source_link="l", mandatory=[LLMSkillFinding(skill="python", match="present")])
    assert compute_score(partial, 4, None, req)[1]["rejected_reason"] == "not screened: Django"


def test_top_skill_comes_from_requirements_not_list_order():
    req = SourcingRequirements(mandatory_skills=[SkillSpec(name="Python"), SkillSpec(name="Django")])
    s = LLMScreenedProfile(source_link="l", mandatory=[
        LLMSkillFinding(skill="Django", match="present", strength="excellent"),
        LLMSkillFinding(skill="Python", match="present", strength="basic"),
    ])
    assert compute_score(s, 4, None, req)[0] == 60  # Django excellent is not the top skill


# 5 — an empty delivery is not "exhausted" unless the extension says results ended
async def test_empty_scrape_without_end_is_not_exhausted(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), ended=False)
    await service.process_page(run_id)
    jd = await SourcingJd.get(jd.id)
    assert jd.pool_exhausted is False and jd.next_page == 1


async def test_results_end_marks_exhausted_and_pages_advance_by_crawled(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    fake_llm.queue(all_present_batch([scraped(1).source_link]))
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks(), ended=True)
    await service.process_page(run_id)
    jd = await SourcingJd.get(jd.id)
    assert jd.pool_exhausted is True and jd.next_page == 2


async def test_source_url_recorded_on_run(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), source_url="https://resdex.naukri.com/v3/search?x=1")
    assert (await SourcingRun.get(run_id)).source_url == "https://resdex.naukri.com/v3/search?x=1"


# 7 — stale runs are visible as finished and don't block delete
async def test_stale_run_expires_on_detail_and_delete():
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcingRun(sourcing_jd_id=str(jd.id), run_no=1, clicked_by=str(user.id), mode="scrape", status="pending",
                      created_at=datetime.now(timezone.utc) - timedelta(minutes=30)).insert()
    assert (await service.get_detail(str(jd.id), user))["active_run"] is None
    await SourcingRun(sourcing_jd_id=str(jd.id), run_no=2, clicked_by=str(user.id), mode="scrape", status="pending",
                      created_at=datetime.now(timezone.utc) - timedelta(minutes=30)).insert()
    await service.delete_jd(str(jd.id), user)
    assert await SourcingJd.get(jd.id) is None
