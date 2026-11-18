import httpx
import pytest
from fastapi import FastAPI

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app.components.auth.dependencies import get_effective_user
from app.components.common.schemas import Role
from app.components.sourcing.routes import router
from app.components.sourcing.schemas import LLMRequirements, LLMSearchPlan, LLMSkill

from tests.sourcing.helpers import JD_TEXT, all_present_batch, make_ready_jd, make_user, scraped


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


async def test_create_list_detail_roundtrip(fake_llm):
    user = await make_user()
    fake_llm.queue(LLMRequirements(role_title="Python Dev", mandatory_skills=[LLMSkill(name="Python")]))
    fake_llm.queue(LLMSearchPlan(primary_keywords="Python"))
    async with client_for(user) as c:
        r = await c.post("/api/sourcing/jds", data={"title": "Py", "jd_text": JD_TEXT})
        assert r.status_code == 200, r.text
        jd_id = r.json()["data"]["id"]
        r = await c.get("/api/sourcing/jds")
        assert r.json()["data"]["total"] == 1
        r = await c.get(f"/api/sourcing/jds/{jd_id}")
        data = r.json()["data"]
        assert data["analysis_status"] == "done"
        assert data["search_plan"]["primary_keywords"] == "Python"
        assert data["pool_count"] == 0


async def test_run_endpoints_flow(fake_llm):
    user = await make_user()
    jd = await make_ready_jd(user)
    fake_llm.queue(all_present_batch([scraped(i).source_link for i in range(3)]))
    async with client_for(user) as c:
        r = await c.post(f"/api/sourcing/jds/{jd.id}/runs")
        assert r.json()["data"]["mode"] == "scrape"
        run_id = r.json()["data"]["run"]["id"]
        r = await c.post(f"/api/sourcing/runs/{run_id}/profiles",
                         json={"profiles": [scraped(i).model_dump() for i in range(3)]})
        assert r.status_code == 202
        assert r.json()["data"]["accepted"] == 3
        r = await c.get(f"/api/sourcing/runs/{run_id}")
        assert r.json()["data"]["status"] == "scraping"            # 3 found — waiting for page 2
        assert r.json()["data"]["next_action"] == "next_page"
        r = await c.get(f"/api/sourcing/jds/{jd.id}/profiles", params={"status": "shortlisted"})
        assert len(r.json()["data"]) == 3
        pid = r.json()["data"][0]["id"]
        r = await c.post(f"/api/sourcing/profiles/{pid}/status", json={"status": "selected"})
        assert r.json()["data"]["needs_contact"] is True
        r = await c.post(f"/api/sourcing/profiles/{pid}/contact", json={"email": "a@b.com"})
        assert r.json()["data"]["profile"]["candidate_user_id"]


async def test_fail_endpoint_validates_reason():
    user = await make_user()
    jd = await make_ready_jd(user)
    async with client_for(user) as c:
        run_id = (await c.post(f"/api/sourcing/jds/{jd.id}/runs")).json()["data"]["run"]["id"]
        r = await c.post(f"/api/sourcing/runs/{run_id}/fail", json={"reason": "whatever"})
        assert r.status_code == 422
        r = await c.post(f"/api/sourcing/runs/{run_id}/fail", json={"reason": "captcha"})
        assert r.json()["data"]["status"] == "failed"


async def test_admin_cannot_start_run():
    owner = await make_user()
    admin = await make_user(email="admin@x.com", role=Role.SUPER_ADMIN)
    jd = await make_ready_jd(owner)
    async with client_for(admin) as c:
        r = await c.post(f"/api/sourcing/jds/{jd.id}/runs")
        assert r.status_code == 403
        r = await c.get(f"/api/sourcing/jds/{jd.id}")
        assert r.status_code == 200
