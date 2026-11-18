from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.components.sourcing import service
from app.components.sourcing.models import SkillSpec, SourcedProfile, SourcingJd, SourcingRequirements, SourcingRun, SourcingSearchPlan
from app.components.sourcing.schemas import LLMRequirements, LLMScreenBatch, LLMSearchPlan, LLMSkill

from tests.sourcing.helpers import JD_TEXT, all_present_batch, make_ready_jd, make_user, scraped


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def _scrape_run(jd, user):
    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert res["mode"] == "scrape"
    return res["run"]["id"]


async def test_create_and_analyze(fake_llm):
    user = await make_user()
    fake_llm.queue(LLMRequirements(role_title="Python Dev", mandatory_skills=[LLMSkill(name="Python")]))
    fake_llm.queue(LLMSearchPlan(primary_keywords="Python", narrowed_keywords=""))
    summary = await service.create_sourcing_jd(user, BackgroundTasks(), title="Py", jd_text=JD_TEXT, jd_file=None)
    assert summary["analysis_status"] == "generating"
    await service.run_analysis(summary["id"])
    jd = await SourcingJd.get(summary["id"])
    assert jd.analysis_status == "done"
    assert jd.requirements_version == 1
    assert jd.search_plan.primary_keywords == "Python"


async def test_create_rejects_short_jd():
    user = await make_user()
    with pytest.raises(HTTPException) as e:
        await service.create_sourcing_jd(user, BackgroundTasks(), title="x", jd_text="too short", jd_file=None)
    assert e.value.status_code == 400


async def test_invalid_jd_marks_failed(fake_llm):
    user = await make_user()
    fake_llm.queue(LLMRequirements(is_valid_jd=False, invalid_reason="Not a JD"))
    summary = await service.create_sourcing_jd(user, BackgroundTasks(), title="Py", jd_text=JD_TEXT, jd_file=None)
    await service.run_analysis(summary["id"])
    jd = await SourcingJd.get(summary["id"])
    assert jd.analysis_status == "failed"
    assert jd.analysis_error == "Not a JD"


async def test_first_click_scrapes_from_page_1():
    user = await make_user()
    jd = await make_ready_jd(user)
    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert res["mode"] == "scrape"
    assert (res["page_from"], res["page_to"]) == (1, 7)  # 5 to hunt + 2 to prefetch, at most
    assert res["run"]["status"] == "pending"
    assert res["search_plan"]["primary_keywords"] == "Python AND Django"


async def test_start_run_requires_analysis_done():
    user = await make_user()
    jd = await make_ready_jd(user, analysis_status="generating")
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks())
    assert e.value.status_code == 400


async def test_receive_dedupes_screens_and_shortlists_five(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source_link=scraped(0).source_link,
                         name="Cand 0", status="rejected").insert()
    run_id = await _scrape_run(jd, user)
    batch = [scraped(i) for i in range(7)] + [scraped(3)]  # 0 is already rejected; 3 is duplicated in batch
    new_links = [scraped(i).source_link for i in range(1, 7)]
    fake_llm.queue(all_present_batch(new_links))
    res = await service.receive_profiles(run_id, batch, user, BackgroundTasks())
    assert res["accepted"] == 6
    await service.process_page(run_id)

    run = await SourcingRun.get(run_id)
    assert run.status == "scraping" and run.phase == "prefetch"  # 5 found on page 1; now filling the pool
    assert run.profiles_received == 8 and run.profiles_new == 6 and run.profiles_shortlisted == 5
    jid = str(jd.id)
    assert await SourcedProfile.find(SourcedProfile.sourcing_jd_id == jid, SourcedProfile.status == "shortlisted").count() == 5
    assert await SourcedProfile.find(SourcedProfile.sourcing_jd_id == jid, SourcedProfile.status == "pool").count() == 1
    assert (await SourcingJd.get(jd.id)).next_page == 2


async def test_second_click_uses_pool_first(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    links = [scraped(i).source_link for i in range(6)]
    fake_llm.queue(all_present_batch(links))
    await service.receive_profiles(run_id, [scraped(i) for i in range(6)], user, BackgroundTasks(), ended=True)
    await service.process_page(run_id)

    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert res["mode"] == "pool"
    assert res["run"]["status"] == "done"
    assert res["run"]["profiles_shortlisted"] == 1
    assert len(fake_llm.calls) == 1  # no new screening


async def test_earlier_statuses_untouched_by_new_run(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    kept = SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source_link="https://x/kept", name="K", status="on_hold", score=90)
    await kept.insert()
    run_id = await _scrape_run(jd, user)
    fake_llm.queue(all_present_batch([scraped(1).source_link]))
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    await service.process_page(run_id)
    assert (await SourcedProfile.get(kept.id)).status == "on_hold"


async def test_profiles_without_link_are_skipped(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    fake_llm.queue(all_present_batch([scraped(1).source_link]))
    res = await service.receive_profiles(run_id, [scraped(9, source_link=""), scraped(1)], user, BackgroundTasks())
    assert res["accepted"] == 1
    await service.process_page(run_id)
    assert await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id)).count() == 1


async def test_unscreened_profile_is_below_threshold(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    fake_llm.queue(all_present_batch([scraped(1).source_link]))  # screener skips profile 2
    await service.receive_profiles(run_id, [scraped(1), scraped(2)], user, BackgroundTasks())
    await service.process_page(run_id)
    p2 = await SourcedProfile.find_one(SourcedProfile.source_link == scraped(2).source_link)
    assert p2.status == "below_threshold"
    assert p2.match_reasons == ["Could not be screened"]
    assert (await SourcingRun.get(run_id)).status == "scraping"  # only 1 match — keeps hunting


async def test_low_score_is_below_threshold(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    fake_llm.queue(all_present_batch([scraped(1).source_link]))
    await service.receive_profiles(run_id, [scraped(1, experience_years=1)], user, BackgroundTasks())
    await service.process_page(run_id)
    p = await SourcedProfile.find_one(SourcedProfile.source_link == scraped(1).source_link)
    assert p.status == "below_threshold" and p.score == 0
    assert p.score_breakdown["rejected_reason"] == "experience out of range"


async def test_second_post_for_run_is_rejected(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    with pytest.raises(HTTPException) as e:
        await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    assert e.value.status_code == 409


async def test_concurrent_run_conflicts():
    user = await make_user()
    jd = await make_ready_jd(user)
    await _scrape_run(jd, user)
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks())
    assert e.value.status_code == 409
    assert e.value.detail == "A sourcing run is already in progress"


async def test_stale_run_does_not_block_new_run():
    user = await make_user()
    jd = await make_ready_jd(user)
    old = SourcingRun(sourcing_jd_id=str(jd.id), run_no=1, clicked_by=str(user.id), mode="scrape",
                      status="scraping", created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    await old.insert()
    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert res["mode"] == "scrape"
    old = await SourcingRun.get(old.id)
    assert old.status == "failed" and old.error == "timed out"


async def test_exhausted_pool_conflicts():
    user = await make_user()
    jd = await make_ready_jd(user, pool_exhausted=True)
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks())
    assert e.value.status_code == 409


async def test_empty_scrape_at_end_of_results_marks_exhausted(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), ended=True)
    await service.process_page(run_id)
    assert (await SourcingJd.get(jd.id)).pool_exhausted is True
    assert (await SourcingRun.get(run_id)).status == "done"


async def test_fail_run_not_logged_in_keeps_next_page():
    user = await make_user()
    jd = await make_ready_jd(user, next_page=6)
    run_id = await _scrape_run(jd, user)
    out = await service.fail_run(run_id, "not_logged_in", "", user)
    assert out["status"] == "failed" and out["error"] == "not_logged_in"
    assert (await SourcingJd.get(jd.id)).next_page == 6


async def test_update_requirements_rescreens_pool_only(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    pool = SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source_link="https://x/pool", name="P",
                          status="pool", score=61, experience_years=4)
    rej = SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source_link="https://x/rej", name="R",
                         status="rejected", score=90)
    await pool.insert()
    await rej.insert()
    new_req = SourcingRequirements(mandatory_skills=[SkillSpec(name="Python"), SkillSpec(name="Django")])
    await service.update_requirements(str(jd.id), new_req, user, BackgroundTasks())
    fake_llm.queue(all_present_batch(["https://x/pool"], strength="strong"))
    await service.rescreen_pool(str(jd.id))
    pool = await SourcedProfile.get(pool.id)
    assert pool.score == 75 and pool.screened_with_version == 2
    rej = await SourcedProfile.get(rej.id)
    assert rej.score == 90 and rej.status == "rejected"


async def test_search_plan_edit_resets_paging():
    user = await make_user()
    jd = await make_ready_jd(user, next_page=11, pool_exhausted=True)
    await service.update_search_plan(str(jd.id), SourcingSearchPlan(primary_keywords="Go"), user)
    jd = await SourcingJd.get(jd.id)
    assert jd.next_page == 1 and jd.pool_exhausted is False
    assert jd.search_plan.primary_keywords == "Go"


async def test_other_recruiter_cannot_read_or_write():
    owner = await make_user()
    other = await make_user(email="other@softsuave.com")
    jd = await make_ready_jd(owner)
    for call in (service.get_detail(str(jd.id), other), service.start_run(str(jd.id), other, BackgroundTasks())):
        with pytest.raises(HTTPException) as e:
            await call
        assert e.value.status_code == 403


async def test_detail_reports_pool_count_and_active_run():
    user = await make_user()
    jd = await make_ready_jd(user)
    await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source_link="https://x/1", name="A", status="pool", score=70).insert()
    detail = await service.get_detail(str(jd.id), user)
    assert detail["pool_count"] == 1
    assert detail["active_run"] is None
    assert detail["counts"]["pool"] == 1
