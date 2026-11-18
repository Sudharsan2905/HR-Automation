"""HTTP-level checks: auth boundaries, mounting under /api, response envelope."""

import httpx
import pytest
from fastapi import FastAPI

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app._core.security import create_access_token
from app.components.level1 import db as l1db
from app.components.level1.routes import router
from tests.level1.conftest import build_exam, make_admin, make_candidate


def token(user, scope: str | None = None) -> dict:
    data = {"sub": str(user.id), "role": user.role.value}
    if scope:
        data["scope"] = scope
    return {"Authorization": f"Bearer {create_access_token(data)}"}


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    from app.components.level1 import scoring_tasks

    monkeypatch.setattr(scoring_tasks, "_RETRY_DELAY_SECONDS", 0)


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_exam_flow_over_http(client):
    user = await make_candidate()
    built = await build_exam([user.email])
    h = token(user, "l1")
    async with client as c:
        r = await c.get(f"/api/level1/exam/assessment/{built['share_link']}", headers=h)
        assert r.status_code == 200 and r.json()["data"]["name"] == "Backend Dev"
        assert (await c.get(f"/api/level1/exam/submission/status?share_link={built['share_link']}", headers=h)).json()["data"] is None
        sub = (await c.post(f"/api/level1/exam/assessment/{built['share_link']}/start", headers=h)).json()["data"]
        rd = (await c.get(f"/api/level1/exam/submission/{sub['id']}/round", headers=h)).json()["data"]
        qid = rd["round"]["questions"][0]["id"]
        r = await c.post(f"/api/level1/exam/submission/{sub['id']}/answer", headers=h, json={"question_id": qid, "answer": ["a"]})
        assert r.json()["data"] == {"saved": True}
        r = await c.post(f"/api/level1/exam/submission/{sub['id']}/malpractice", headers=h, data={"type": "tab_switch"})
        assert r.json()["data"]["malpractice_count"] == 1
        r = await c.post(f"/api/level1/exam/submission/{sub['id']}/screenshot", headers=h, files={"file": ("s.jpg", b"img", "image/jpeg")})
        assert r.status_code == 200
        r = await c.post(f"/api/level1/exam/submission/{sub['id']}/malpractice", headers=h, data={"type": "bogus"})
        assert r.status_code == 422
        r = await c.get(f"/api/level1/exam/submission/{sub['id']}/session-state", headers=h)
        assert r.json()["data"]["status"] == "in_progress"


async def test_exam_endpoints_reject_non_l1_tokens(client):
    user = await make_candidate()
    admin = await make_admin()
    built = await build_exam([user.email])
    url = f"/api/level1/exam/assessment/{built['share_link']}"
    async with client as c:
        assert (await c.get(url)).status_code in (401, 403)
        assert (await c.get(url, headers=token(user, "l2"))).status_code == 403
        assert (await c.get(url, headers=token(admin))).status_code == 403


async def test_admin_endpoints_need_admin_and_work(client):
    user = await make_candidate()
    admin = await make_admin()
    built = await build_exam([user.email])
    from app.components.level1 import candidate_service

    sub = await candidate_service.start_assessment(l1db.get_db(), built["share_link"], str(user.id))
    base = f"/api/level1/assessments/{built['assessment_id']}/submissions"
    async with client as c:
        assert (await c.get(base, headers=token(user, "l1"))).status_code == 403
        assert (await c.get(base)).status_code in (401, 403)
        r = await c.get(base, headers=token(admin))
        assert r.json()["data"]["submissions"][0]["candidate_email"] == user.email
        r = await c.get(f"{base}/{sub['id']}", headers=token(admin))
        assert r.status_code == 200 and len(r.json()["data"]["rounds"][0]["questions"]) == 20
        r = await c.post(f"{base}/{sub['id']}/terminate", headers=token(admin), json={"reason": "test"})
        assert r.json()["data"] == {"terminated": True}
        r = await c.post(f"{base}/{sub['id']}/complete", headers=token(admin))
        assert r.status_code == 403
