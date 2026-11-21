"""The HTTP contract between SkillMate and the LinkedIn extension: the run endpoint takes a source, and the
page endpoint accepts exactly what linkedin_sourcing/linkedin.js sends."""

import httpx
import pytest
from fastapi import FastAPI

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app.components.auth.dependencies import get_effective_user
from app.components.sourcing.routes import router
from app.components.sourcing.schemas import LLMScreenBatch, LLMScreenedProfile, LLMSkillFinding

from tests.sourcing.helpers import make_ready_jd, make_user


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


def client_for(user) -> httpx.AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def card(i: int, **kw) -> dict:
    """Exactly the keys linkedin.js › toProfile() produces (no experience_years / current_ctc_lacs)."""
    data = {
        "name": f"Li {i}", "headline": "Python Developer | Django", "snippet": "Summary: built Django apps",
        "location": "Chennai, Tamil Nadu, India", "source": "LinkedIn",
        "source_link": f"https://www.linkedin.com/in/li-{i}", "email": f"li{i}@example.com", "phone": "",
        "skills": ["Python"], "experiences": [{"company": "Zoho", "title": "Developer", "duration": "",
                                               "is_current": True, "starts_at": {}, "ends_at": {}}],
        "education": [], "total_experience": "", "current_ctc": "", "connection_degree": "2nd",
    }
    data.update(kw)
    return data


def batch(links, **match) -> LLMScreenBatch:
    return LLMScreenBatch(profiles=[
        LLMScreenedProfile(source_link=link, mandatory=[
            LLMSkillFinding(skill="Python", match=match.get("python", "present"), strength="basic"),
            LLMSkillFinding(skill="Django", match=match.get("django", "present"), strength="basic")])
        for link in links])


async def test_run_endpoint_takes_a_source_and_defaults_to_naukri():
    user = await make_user()
    jd = await make_ready_jd(user)
    async with client_for(user) as c:
        r = await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["source"] == "linkedin" and data["run"]["source"] == "linkedin"
        await c.post(f"/api/sourcing/runs/{data['run']['id']}/fail", json={"reason": "cancelled"})

        for body in ({}, None):                      # what the Naukri flow has always sent, and no body at all
            kwargs = {} if body is None else {"json": body}
            r = await c.post(f"/api/sourcing/jds/{jd.id}/runs", **kwargs)
            assert r.status_code == 200, r.text
            assert r.json()["data"]["run"]["source"] == "naukri"
            await c.post(f"/api/sourcing/runs/{r.json()['data']['run']['id']}/fail", json={"reason": "cancelled"})


async def test_unknown_source_is_a_validation_error():
    user = await make_user()
    jd = await make_ready_jd(user)
    async with client_for(user) as c:
        r = await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "indeed"})
        assert r.status_code == 422


async def test_linkedin_page_in_screening_out_and_the_detail_exposes_both_sources(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    links = [card(i)["source_link"] for i in range(3)]
    fake_llm.queue(batch(links, django="absent"))   # the card doesn't show Django
    async with client_for(user) as c:
        run = (await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})).json()["data"]["run"]
        r = await c.post(f"/api/sourcing/runs/{run['id']}/profiles",
                         json={"profiles": [card(i) for i in range(3)], "ended": False,
                               "source_url": "https://www.linkedin.com/search/results/people/?page=1"})
        assert r.status_code == 202 and r.json()["data"]["accepted"] == 3

        # the extension's next call is the poll: screening runs in the background task, so wait for it
        from app.components.sourcing import service
        await service.process_page(run["id"])
        r = await c.get(f"/api/sourcing/jds/{jd.id}/profiles", params={"status": "shortlisted"})
        rows = r.json()["data"]
        assert len(rows) == 3 and {p["source"] for p in rows} == {"LinkedIn"}
        assert all(p["score"] == 60 for p in rows)
        assert all("not shown on the LinkedIn card" in n for p in rows for n in p["related_notes"])

        detail = (await c.get(f"/api/sourcing/jds/{jd.id}")).json()["data"]
        assert (detail["linkedin_next_page"], detail["linkedin_exhausted"]) == (2, False)
        assert (detail["next_page"], detail["pool_exhausted"]) == (1, False)       # Naukri's paging untouched
        assert detail["runs"][0]["source"] == "linkedin"

        full = (await c.get(f"/api/sourcing/profiles/{rows[0]['id']}")).json()["data"]
        assert full["source"] == "LinkedIn" and full["headline"].startswith("Python Developer")


async def test_fail_endpoint_accepts_the_reasons_the_linkedin_extension_sends():
    user = await make_user()
    jd = await make_ready_jd(user)
    async with client_for(user) as c:
        for reason in ("restricted", "captcha", "not_logged_in", "error"):
            run = (await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})).json()["data"]["run"]
            r = await c.post(f"/api/sourcing/runs/{run['id']}/fail", json={"reason": reason, "detail": "page 2"})
            assert r.status_code == 200, (reason, r.text)
            assert r.json()["data"]["status"] == "failed"
        r = await c.post(f"/api/sourcing/runs/{run['id']}/fail", json={"reason": "weird"})
        assert r.status_code == 422
