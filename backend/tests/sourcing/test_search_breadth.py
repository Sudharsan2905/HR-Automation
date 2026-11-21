"""Regression: a JD whose analysis listed soft skills as mandatory produced a search no profile can match.

The real case: ten mandatory skill groups ANDed, including "Problem-solving" and "Communication skills" in quotes ->
LinkedIn returned nobody -> the run failed with no_results."""

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.components.sourcing import agents, service
from app.components.sourcing.models import SkillSpec, SourcingRequirements
from app.components.sourcing.schemas import LLMRequirements, LLMSearchPlan, LLMSkill
from app.components.sourcing.prompt import JD_ANALYST_PROMPT

from tests.sourcing.helpers import make_ready_jd, make_user


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


# What the analyst returned for the "full stack" JD, in order.
FULL_STACK = [
    ("HTML5", ["HTML5", "HTML"]), ("CSS3", ["CSS3", "CSS"]), ("JavaScript", ["JavaScript", "JS"]),
    ("Angular", ["Angular", "React"]), ("Node.js", ["Node.js", "NodeJS", "Node"]), ("MySQL", ["MySQL", "PostgreSQL"]),
    ("Git", ["Git"]), ("API security", ["API security", "authentication", "authorization"]),
    ("Problem-solving", ["Problem-solving"]), ("Communication skills", ["Communication skills"]),
]


async def test_soft_skills_are_dropped_from_mandatory_and_preferred(fake_llm):
    fake_llm.queue(LLMRequirements(
        role_title="Full Stack Developer",
        mandatory_skills=[LLMSkill(name=n, variants=v) for n, v in FULL_STACK],
        preferred_skills=[LLMSkill(name="TypeScript"), LLMSkill(name="Teamwork"), LLMSkill(name="Docker")],
    ))
    req = await agents.analyze_jd("Full stack developer ...")
    assert [s.name for s in req.mandatory_skills] == [n for n, _ in FULL_STACK[:8]]
    assert [s.name for s in req.preferred_skills] == ["TypeScript", "Docker"]


async def test_the_cap_counts_technical_skills_only(fake_llm):
    fake_llm.queue(LLMRequirements(mandatory_skills=[
        LLMSkill(name="Communication skills"), LLMSkill(name="Leadership"),
        *[LLMSkill(name=f"Tech{i}") for i in range(12)]]))
    req = await agents.analyze_jd("x")
    assert [s.name for s in req.mandatory_skills] == [f"Tech{i}" for i in range(10)]


async def test_technical_terms_that_merely_resemble_soft_skills_are_kept(fake_llm):
    fake_llm.queue(LLMRequirements(mandatory_skills=[
        LLMSkill(name="Communication protocols"), LLMSkill(name="API security"), LLMSkill(name="Problem Solving in Algorithms")]))
    req = await agents.analyze_jd("x")
    assert len(req.mandatory_skills) == 3


async def test_search_is_built_from_the_most_central_skills_only(fake_llm):
    req = SourcingRequirements(mandatory_skills=[SkillSpec(name=n, variants=v) for n, v in FULL_STACK[:8]],
                               preferred_skills=[SkillSpec(name="TypeScript")])
    fake_llm.queue(LLMSearchPlan(primary_keywords="HTML5", narrowed_keywords="HTML5"))
    await agents.build_search_plan(req)
    prompt = fake_llm.calls[-1][0]
    for name, _ in FULL_STACK[:agents.SEARCH_MAX_SKILLS]:
        assert f'"name": "{name}"' in prompt
    for name, _ in FULL_STACK[agents.SEARCH_MAX_SKILLS:8]:
        assert f'"name": "{name}"' not in prompt          # screened on later, but not ANDed into the search
    assert '"name": "TypeScript"' in prompt                # preferred skills still shape the narrowed search


async def test_screening_still_requires_every_mandatory_skill(fake_llm):
    """Only the SEARCH is shortened: the requirements the screener and scorer use keep all mandatory skills."""
    fake_llm.queue(LLMRequirements(mandatory_skills=[LLMSkill(name=n, variants=v) for n, v in FULL_STACK]))
    req = await agents.analyze_jd("x")
    assert len(req.mandatory_skills) == 8 > agents.SEARCH_MAX_SKILLS


def test_the_analyst_prompt_forbids_soft_skills_and_orders_by_centrality():
    assert "NEVER list soft skills" in JD_ANALYST_PROMPT
    assert "first 5" in JD_ANALYST_PROMPT


# ── a failure reported twice (extension + page) ───────────────────────────────────

async def _scrape_run(jd, user):
    return (await service.start_run(str(jd.id), user, BackgroundTasks(), source="linkedin"))["run"]["id"]


async def test_reporting_the_same_failure_twice_is_a_quiet_no_op():
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    first = await service.fail_run(run_id, "error", "no_results", user)
    again = await service.fail_run(run_id, "error", "no_results", user)       # the page's duplicate report
    assert first["status"] == again["status"] == "failed"
    assert again["error"] == "error: no_results"
    cancelled = await service.fail_run(run_id, "cancelled", "", user)          # first outcome wins
    assert cancelled["status"] == "failed" and cancelled["error"] == "error: no_results"


async def test_a_finished_run_still_cannot_be_failed():
    from app.components.sourcing.models import SourcingRun
    user = await make_user()
    jd = await make_ready_jd(user)
    run = SourcingRun(sourcing_jd_id=str(jd.id), run_no=1, clicked_by=str(user.id), mode="scrape", status="done")
    await run.insert()
    with pytest.raises(HTTPException) as e:
        await service.fail_run(str(run.id), "error", "x", user)
    assert e.value.status_code == 409


# ── re-analysis ─────────────────────────────────────────────────────────────────────

async def test_reanalyze_is_refused_while_a_run_is_active_and_allowed_after():
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    with pytest.raises(HTTPException) as e:
        await service.reanalyze(str(jd.id), user, BackgroundTasks())
    assert e.value.status_code == 409
    await service.fail_run(run_id, "cancelled", "", user)
    out = await service.reanalyze(str(jd.id), user, BackgroundTasks())
    assert out == {"message": "Re-analysis started"}


# ── a failed run keeps what the extension saw ──────────────────────────────────────────

async def test_a_failed_run_keeps_the_evidence_and_the_first_report_wins():
    from app.components.sourcing.models import SourcingRun
    user = await make_user()
    jd = await make_ready_jd(user)
    run_id = await _scrape_run(jd, user)
    evidence = 'L0@p1 v1.1.0: cards=0 profiles=0 no-results-page anchors=0 title="Search | LinkedIn" text="No results found"'
    out = await service.fail_run(run_id, "error", "no_results", user, debug=evidence)
    assert out["debug"] == evidence and out["error"] == "error: no_results"
    again = await service.fail_run(run_id, "error", "no_results", user, debug="the page's own duplicate report")
    assert again["debug"] == evidence                                       # not overwritten by the duplicate
    assert (await SourcingRun.get(run_id)).debug == evidence


async def test_debug_is_capped_and_optional_over_http():
    import httpx
    from fastapi import FastAPI
    from app._core.handler import register_exception_handlers
    from app._core.middleware import GlobalResponseMiddleware
    from app.components.auth.dependencies import get_effective_user
    from app.components.sourcing.routes import router

    user = await make_user()
    jd = await make_ready_jd(user)
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(GlobalResponseMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_effective_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        run = (await c.post(f"/api/sourcing/jds/{jd.id}/runs", json={"source": "linkedin"})).json()["data"]["run"]
        r = await c.post(f"/api/sourcing/runs/{run['id']}/fail", json={"reason": "error", "detail": "x", "debug": "d" * 1001})
        assert r.status_code == 422
        r = await c.post(f"/api/sourcing/runs/{run['id']}/fail", json={"reason": "error", "detail": "no_results"})   # older extensions
        assert r.status_code == 200 and r.json()["data"]["debug"] == ""


# ── text that is not a JD, or a JD with nothing to search on ─────────────────────────────────

async def test_a_jd_with_no_technical_skills_is_refused_with_a_clear_message(fake_llm):
    """The real case: the pasted text was an instruction sentence naming a file; the model guessed skills from the
    file name. And a JD made only of soft skills has nothing to search on either."""
    fake_llm.queue(LLMRequirements(role_title="Full Stack Developer", mandatory_skills=[]))
    with pytest.raises(ValueError, match="does not list any required skills"):
        await agents.analyze_jd("paste the whole text from Full_Stack_Developer_React_Node_JD.txt")
    fake_llm.queue(LLMRequirements(mandatory_skills=[LLMSkill(name="Communication skills"), LLMSkill(name="Teamwork")]))
    with pytest.raises(ValueError, match="Delete this JD"):
        await agents.analyze_jd("We need someone with good communication and teamwork")


async def test_the_failure_reaches_the_jd_so_the_recruiter_sees_why(fake_llm):
    from app.components.sourcing.models import SourcingJd
    user = await make_user()
    jd = await make_ready_jd(user, analysis_status="generating")
    fake_llm.queue(LLMRequirements(mandatory_skills=[]))
    await service.run_analysis(str(jd.id))
    fresh = await SourcingJd.get(jd.id)
    assert fresh.analysis_status == "failed" and "does not list any required skills" in fresh.analysis_error


def test_the_analyst_prompt_rejects_text_about_a_file():
    assert "Never take a skill, role, number or company from a file name" in JD_ANALYST_PROMPT
    assert '"paste"' in JD_ANALYST_PROMPT
