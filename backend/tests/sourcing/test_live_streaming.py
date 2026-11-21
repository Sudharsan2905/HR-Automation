"""Live sourcing: people are stored and screened as they arrive, and show up shortlisted one by one
instead of all at once when a whole page has been read and screened."""
import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

from app._core.settings import settings
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile, SourcingRun

from tests.sourcing.helpers import all_present_batch, make_ready_jd, make_user, scraped


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def _start(jd, user):
    return (await service.start_run(str(jd.id), user, BackgroundTasks()))["run"]["id"]


async def _stream(run_id, user, fake_llm, i):
    """Send one person the way the extension does, and let their screening finish."""
    fake_llm.queue(all_present_batch([scraped(i).source_link]))
    out = await service.receive_stream(run_id, [scraped(i)], user)
    await service._wait_inflight(run_id)
    return out


async def _profile(i) -> SourcedProfile:
    return await SourcedProfile.find_one(SourcedProfile.source_link == scraped(i).source_link)


async def test_each_streamed_person_is_shortlisted_before_the_page_ends(fake_llm):
    user = await make_user()
    run_id = await _start(await make_ready_jd(user), user)

    for i in range(3):
        assert (await _stream(run_id, user, fake_llm, i))["accepted"] == 1
        p = await _profile(i)
        assert p.status == "shortlisted" and p.score is not None and p.shortlisted_in_run_id == run_id
        assert (await SourcingRun.get(run_id)).profiles_shortlisted == i + 1

    run = await SourcingRun.get(run_id)
    assert (run.profiles_received, run.profiles_new) == (3, 3)
    assert (run.status, run.next_action) == ("pending", "next_page")      # still reading the page


async def test_only_the_first_five_take_a_shortlist_place_and_the_page_end_does_not_screen_again(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _start(jd, user)

    for i in range(6):
        await _stream(run_id, user, fake_llm, i)
    assert (await _profile(5)).status == "pool"                              # no place left: kept for the next click
    assert (await SourcingRun.get(run_id)).profiles_shortlisted == 5

    # The page ends: everyone was sent already, so only the page is closed.
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=6)
    await service.process_page(run_id)

    run = await SourcingRun.get(run_id)
    assert run.profiles_shortlisted == 5 and run.phase == "prefetch"
    assert (run.status, run.next_action, run.pages_crawled) == ("scraping", "next_page", 1)
    assert len(fake_llm.calls) == 6                                          # nobody was screened twice
    shortlisted = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == str(jd.id),
                                            SourcedProfile.status == "shortlisted").count()
    assert shortlisted == 5


async def test_a_person_sent_twice_is_stored_once(fake_llm):
    user = await make_user()
    run_id = await _start(await make_ready_jd(user), user)
    await _stream(run_id, user, fake_llm, 1)
    out = await service.receive_stream(run_id, [scraped(1)], user)
    assert out["accepted"] == 0
    assert await SourcedProfile.find(SourcedProfile.source_link == scraped(1).source_link).count() == 1


async def test_streaming_is_refused_once_the_page_has_been_posted(fake_llm):
    user = await make_user()
    run_id = await _start(await make_ready_jd(user), user)
    await service.receive_profiles(run_id, [], user, BackgroundTasks(), scanned=1)   # page closed, run is screening
    with pytest.raises(HTTPException) as e:
        await service.receive_stream(run_id, [scraped(1)], user)
    assert e.value.status_code == 409


async def test_a_page_screens_chunk_by_chunk_so_early_matches_do_not_wait_for_the_slowest(monkeypatch):
    """Naukri posts a whole page at once: the first chunk to come back must be saved (and shortlisted) while the
    other chunks are still being screened."""
    monkeypatch.setattr(settings, "SOURCING_SCREEN_CHUNK", 1)
    gates = {scraped(i).source_link: asyncio.Event() for i in range(1, 4)}

    class GatedLLM:
        async def generate_structured(self, prompt, response_schema, **kwargs):
            link = next(l for l in gates if f'"{l}"' in prompt)
            await gates[link].wait()
            return all_present_batch([link])

    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: GatedLLM())
    user = await make_user()
    run_id = await _start(await make_ready_jd(user), user)
    await service.receive_profiles(run_id, [scraped(i) for i in range(1, 4)], user, BackgroundTasks())

    task = asyncio.create_task(service.process_page(run_id))
    gates[scraped(2).source_link].set()                                      # only the second one comes back
    for _ in range(100):
        if (await _profile(2)).status == "shortlisted":
            break
        await asyncio.sleep(0.02)
    assert (await _profile(2)).status == "shortlisted"
    assert (await _profile(1)).score is None and (await _profile(3)).score is None   # still being screened
    assert (await SourcingRun.get(run_id)).profiles_shortlisted == 1

    for g in gates.values():
        g.set()
    await task
    run = await SourcingRun.get(run_id)
    assert run.profiles_shortlisted == 3
