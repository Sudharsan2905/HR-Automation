"""Page-by-page sourcing: screen each ResDex page as it arrives, stop once 5 are shortlisted,
then read 2 more pages into the pool. Leftover unscored profiles are screened before ResDex."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException

from app._core.settings import settings
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun

from tests.sourcing.helpers import all_present_batch, make_ready_jd, make_user, scraped


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def _start(jd, user):
    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert res["mode"] == "scrape"
    return res["run"]["id"]


async def _page(run_id, user, fake_llm, ids, good=None, ended=False):
    """Post one ResDex page; `good` = ids the screener passes (default: all)."""
    good = ids if good is None else good
    if good:
        fake_llm.queue(all_present_batch([scraped(i).source_link for i in good]))
    await service.receive_profiles(run_id, [scraped(i) for i in ids], user, BackgroundTasks(), ended=ended)
    await service.process_page(run_id)
    return await SourcingRun.get(run_id)


async def _count(jd, status):
    return await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id), SourcedProfile.status == status).count()


async def test_first_page_with_five_matches_shortlists_and_reads_two_more_for_the_pool(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)

    run = await _page(run_id, user, fake_llm, range(6))
    assert run.profiles_shortlisted == 5
    assert (run.status, run.phase, run.next_action) == ("scraping", "prefetch", "next_page")
    assert (await SourcingJd.get(jd.id)).next_page == 2

    run = await _page(run_id, user, fake_llm, range(6, 9))      # prefetch page 1 of 2
    assert run.profiles_shortlisted == 5 and run.next_action == "next_page"
    run = await _page(run_id, user, fake_llm, range(9, 11))     # prefetch page 2 of 2
    assert run.status == "done" and run.next_action is None
    assert await _count(jd, "shortlisted") == 5
    assert await _count(jd, "pool") == 1 + 3 + 2                # page-1 extra + both prefetch pages
    assert (await SourcingJd.get(jd.id)).next_page == 4


async def test_short_page_keeps_hunting_on_the_next_page(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)
    run = await _page(run_id, user, fake_llm, range(4), good=[0, 1])
    assert run.profiles_shortlisted == 2
    assert (run.status, run.phase, run.next_action) == ("scraping", "hunting", "next_page")
    run = await _page(run_id, user, fake_llm, range(4, 8))
    assert run.profiles_shortlisted == 5 and run.phase == "prefetch"


async def test_hunting_stops_after_the_page_limit(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)
    for n in range(settings.SOURCING_PAGES_PER_RUN):
        run = await _page(run_id, user, fake_llm, [100 + n], good=[])
    assert run.status == "done" and run.profiles_shortlisted == 0
    assert (await SourcingJd.get(jd.id)).next_page == settings.SOURCING_PAGES_PER_RUN + 1


async def test_end_of_results_finishes_and_marks_exhausted(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)
    run = await _page(run_id, user, fake_llm, range(2), ended=True)
    assert run.status == "done" and run.profiles_shortlisted == 2
    assert (await SourcingJd.get(jd.id)).pool_exhausted is True


async def test_page_is_refused_while_the_previous_one_is_screening(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    with pytest.raises(HTTPException) as e:
        await service.receive_profiles(run_id, [scraped(2)], user, BackgroundTasks())
    assert e.value.status_code == 409


async def test_first_click_returns_upper_page_bound_including_prefetch():
    user = await make_user()
    jd = await make_ready_jd(user)
    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert (res["page_from"], res["page_to"]) == (1, settings.SOURCING_PAGES_PER_RUN + settings.SOURCING_PREFETCH_PAGES)
    assert res["run"]["next_action"] == "next_page"


async def test_unscored_pool_is_screened_before_resdex_and_stops_at_five(fake_llm, monkeypatch):
    monkeypatch.setattr("app.components.sourcing.agents.settings.SOURCING_SCREEN_CHUNK", 2)
    monkeypatch.setattr("app.components.sourcing.service.settings.SOURCING_SCREEN_CHUNK", 2)
    monkeypatch.setattr("app.components.sourcing.service.settings.SOURCING_SCREEN_CONCURRENCY", 1)
    user = await make_user()
    jd = await make_ready_jd(user)
    for i in range(8):
        await SourcedProfile(sourcing_jd_id=str(jd.id), run_id="old", source_link=scraped(i).source_link,
                             name=f"Cand {i}", experience_years=4, status="pool").insert()
    for pair in ([0, 1], [2, 3], [4, 5]):
        fake_llm.queue(all_present_batch([scraped(i).source_link for i in pair]))

    res = await service.start_run(str(jd.id), user, BackgroundTasks())
    assert res["mode"] == "pool" and res["run"]["status"] == "screening"
    await service.process_pool_run(res["run"]["id"])

    run = await SourcingRun.get(res["run"]["id"])
    assert run.status == "done" and run.profiles_shortlisted == 5
    assert len(fake_llm.calls) == 3                       # stopped once 5 were found
    unscored = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id),
                                         SourcedProfile.score == None).count()  # noqa: E711
    assert unscored == 2                                  # left for the next click


async def test_cancel_while_screening_is_allowed_and_not_overwritten(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)
    fake_llm.queue(all_present_batch([scraped(1).source_link]))
    await service.receive_profiles(run_id, [scraped(1)], user, BackgroundTasks())
    out = await service.fail_run(run_id, "cancelled", "", user)
    assert out["status"] == "cancelled"
    await service.process_page(run_id)
    assert (await SourcingRun.get(run_id)).status == "cancelled"


async def test_stale_check_uses_last_activity_not_start_time():
    user = await make_user()
    jd = await make_ready_jd(user)
    now = datetime.now(timezone.utc)
    busy = SourcingRun(sourcing_jd_id=str(jd.id), run_no=1, clicked_by=str(user.id), mode="scrape",
                       status="scraping", created_at=now - timedelta(minutes=40), updated_at=now - timedelta(minutes=1))
    await busy.insert()
    with pytest.raises(HTTPException) as e:
        await service.start_run(str(jd.id), user, BackgroundTasks())
    assert e.value.status_code == 409
