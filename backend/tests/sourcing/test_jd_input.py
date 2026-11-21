"""Creating a JD from pasted text and/or an uploaded PDF/DOCX.

Regression: pasted text always beat the uploaded file, so "full stack development" (22 characters) plus a valid
PDF was rejected with "Please provide a job description" while the PDF was ignored."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app.components.auth.dependencies import get_effective_user
from app.components.sourcing import service
from app.components.sourcing.routes import router
from app.components.sourcing.schemas import LLMRequirements, LLMSearchPlan, LLMSkill

from tests.sourcing.helpers import JD_TEXT, make_user

FILE_JD = "Full stack developer with React and Node.js, 3 to 6 years, Chennai. " * 3
PDF = SimpleNamespace(filename="Full_Stack_Developer_Job_Description.pdf")


@pytest.fixture
def parse(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=FILE_JD)
    monkeypatch.setattr(service, "parse_resume", mock)
    return mock


async def test_short_paste_does_not_hide_an_uploaded_file(parse):
    text = await service._read_jd_input("full stack development", PDF)
    assert text == FILE_JD.strip()
    parse.assert_awaited_once()


async def test_a_real_pasted_jd_still_wins_over_the_file(parse):
    assert await service._read_jd_input(JD_TEXT, PDF) == JD_TEXT.strip()
    parse.assert_not_awaited()


async def test_file_alone_is_parsed(parse):
    assert await service._read_jd_input("", PDF) == FILE_JD.strip()
    assert await service._read_jd_input(None, PDF) == FILE_JD.strip()


async def test_short_paste_without_a_file_says_how_short_it_is():
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("full stack development", None)
    assert e.value.status_code == 400
    assert "pasted job description is too short" in e.value.detail and "22 characters" in e.value.detail
    assert str(service.MIN_JD_CHARS) in e.value.detail


async def test_nothing_at_all_asks_for_text_or_a_file():
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("  ", None)
    assert e.value.status_code == 400 and "paste the text or upload" in e.value.detail


async def test_a_file_that_is_itself_too_short_is_named_as_the_problem(parse):
    parse.return_value = "Developer wanted"
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("full stack development", PDF)
    assert e.value.status_code == 400 and "in the file is too short" in e.value.detail


async def test_unreadable_file_reports_the_file(parse):
    parse.side_effect = ValueError("Unsupported file type")
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("full stack development", PDF)
    assert (e.value.status_code, e.value.detail) == (400, "Unsupported file type")
    parse.side_effect = RuntimeError("boom")
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("", PDF)
    assert e.value.detail == "Could not read the JD file"
    parse.side_effect = None
    parse.return_value = "   "
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("", PDF)
    assert "No text found" in e.value.detail


async def test_too_long_is_still_refused(parse, monkeypatch):
    monkeypatch.setattr(service.settings, "JD_MAX_CHARS", 100)
    with pytest.raises(HTTPException) as e:
        await service._read_jd_input("x" * 101, None)
    assert "too long" in e.value.detail


async def test_the_screenshot_request_over_http_creates_the_jd_from_the_pdf(parse, monkeypatch, fake_llm):
    """multipart POST /sourcing/jds with title, a short jd_text and a PDF — exactly what the dialog sends."""
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)
    fake_llm.queue(LLMRequirements(role_title="Full Stack Developer", mandatory_skills=[LLMSkill(name="React")]))
    fake_llm.queue(LLMSearchPlan(primary_keywords="React"))
    user = await make_user()
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/sourcing/jds", data={"title": "full stack", "jd_text": "full stack development"},
                         files={"jd_file": ("Full_Stack_Developer_Job_Description.pdf", b"%PDF-1.4 fake", "application/pdf")})
        assert r.status_code == 200, r.text
        jd_id = r.json()["data"]["id"]
        detail = (await c.get(f"/api/sourcing/jds/{jd_id}")).json()["data"]
        assert detail["jd_text"] == FILE_JD.strip() and detail["analysis_status"] == "done"
        # and without the PDF the same short text is refused with a message that explains why
        r = await c.post("/api/sourcing/jds", data={"title": "full stack", "jd_text": "full stack development"})
        assert r.status_code == 400 and "22 characters" in r.json()["message"]
