"""Pipeline: contact extraction, question agent, end-to-end run, invites, add_candidates."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.components.auth.models import User
from app.components.level1 import contact_extractor, pipeline_service
from app.components.level1 import db as l1db
from app.components.level1.agents import assessment_agent, question_agent
from tests.level1.conftest import make_candidate, make_questions

ANALYSIS = {"name": "Asha Rao", "email": None, "match_score": 80, "matched_skills": ["python"],
            "missing_skills": [], "focus_topics": ["fastapi"], "suitable": True}
PROFILE = "Python developer with five years of FastAPI experience building APIs."


def cand_input(user: User, **kw) -> dict:
    return {"user_id": str(user.id), "name": user.full_name, "email": user.email,
            "profile_text": PROFILE, "description": "", **kw}


class TestContactExtractor:
    def test_email_prefers_profile(self):
        assert contact_extractor.resolve_email("a@x.com cv", "b@y.com") == ("a@x.com", "profile")

    def test_email_falls_back_to_description(self):
        assert contact_extractor.resolve_email("no mail", "Email: B@Y.com") == ("b@y.com", "description")

    def test_no_email(self):
        assert contact_extractor.resolve_email("none", "none") == (None, None)


class TestQuestionAgent:
    async def test_exact_counts_with_repair(self):
        qs = make_questions()
        first, second = [q for q in qs if q["question_type"] != "essay"] + [q for q in qs if q["question_type"] == "essay"][:2], [q for q in qs if q["question_type"] == "essay"][2:]
        with patch.object(question_agent, "_request", AsyncMock(side_effect=[first, second])):
            out = await question_agent.generate_questions("jd" * 30, [{"name": "A"}])
        assert len(out) == 20 and sum(q["question_type"] == "essay" for q in out) == 4

    async def test_essay_without_model_answer_rejected_and_repaired(self):
        no_answer = [{"question_text": f"Explain topic {i} in detail", "question_type": "essay", "complexity": "low"} for i in range(4)]
        qs = make_questions()
        first = [q for q in qs if q["question_type"] != "essay"] + no_answer
        assert question_agent._normalize(no_answer[0]) is None
        essays = [q for q in qs if q["question_type"] == "essay"]
        with patch.object(question_agent, "_request", AsyncMock(side_effect=[first, essays])):
            out = await question_agent.generate_questions("jd" * 30, [{"name": "A"}])
        assert all(len(q["correct_answer"]) >= 40 for q in out if q["question_type"] == "essay")

    def test_invalid_mcq_dropped(self):
        bad = {"question_text": "bad question here", "question_type": "mcq_single", "complexity": "low",
               "options": [{"text": "a", "is_correct": False}]}
        assert question_agent._normalize(bad) is None

    async def test_builder_guards_missing_model_answer(self):
        with pytest.raises(ValueError):
            await assessment_agent.build_assessment(
                l1db.get_db(), hiring_jd_id="j", user_id="u", jd_title="T", duration_minutes=10, candidate_emails=[],
                questions=[{"question_text": "Explain X", "question_type": "essay", "complexity": "low"}])


def patches(mail):
    return (
        patch("app.components.level1.agents.analysis_agent.chat_json", AsyncMock(return_value=ANALYSIS)),
        patch("app.components.level1.agents.question_agent._request", AsyncMock(return_value=make_questions())),
        patch("app.components.level1.invite_service.send_email", mail),
    )


async def run_to_end(candidates, mail):
    p1, p2, p3 = patches(mail)
    with p1, p2, p3:
        pid = await pipeline_service.start_run(hiring_jd_id="jd1", jd_title="Backend Dev", jd_text="x" * 40,
                                               candidates=candidates, created_by="admin1")
        await asyncio.gather(*pipeline_service._tasks)
    return pid


class TestPipeline:
    async def test_end_to_end_invites_with_key(self):
        user = await make_candidate()
        mail = AsyncMock(return_value=True)
        pid = await run_to_end([cand_input(user)], mail)
        run = await pipeline_service.get_run(pid)
        assert run["status"] == "done" and run["hiring_jd_id"] == "jd1"
        assert run["assessment_id"] and run["share_link"]
        assert [s["status"] for s in run["steps"]] == ["done"] * 5
        assert run["candidates"][0]["status"] == "invited" and run["candidates"][0]["user_id"] == str(user.id)
        assert "profile_text" not in run["candidates"][0]
        assert await l1db.get_db()[l1db.QUESTIONS].count_documents({}) == 20
        mail.assert_awaited_once()
        to, subject, body = mail.await_args.args
        refreshed = await User.get(user.id)
        assert to == user.email and refreshed.level1_key in body
        assert f"/exam/{run['share_link']}" in body and user.email in body
        share = await l1db.get_db()[l1db.SHARES].find_one({})
        assert share["restricted_emails"] == [user.email]
        assert (await pipeline_service.find_run_for_jd("jd1"))["id"] == pid
        assert await pipeline_service.find_run_for_jd("nope") is None

    async def test_failed_step_marks_run_failed_and_skips_rest(self):
        user = await make_candidate()
        with patch("app.components.level1.agents.analysis_agent.chat_json", AsyncMock(side_effect=HTTPException(502, "boom"))):
            pid = await pipeline_service.start_run(hiring_jd_id="jd1", jd_title="T", jd_text="x" * 40,
                                                   candidates=[cand_input(user)], created_by="a")
            await asyncio.gather(*pipeline_service._tasks)
        run = await pipeline_service.get_run(pid)
        statuses = {s["key"]: s["status"] for s in run["steps"]}
        assert run["status"] == "failed" and run["failed_step"] == "analysis"
        assert statuses["analysis"] == "failed" and statuses["questions"] == "skipped"

    async def test_non_candidate_user_is_not_modified(self):
        admin = User(email="boss@example.com", role="super_admin", full_name="Boss")
        await admin.insert()
        mail = AsyncMock(return_value=True)
        pid = await run_to_end([cand_input(admin)], mail)
        run = await pipeline_service.get_run(pid)
        assert run["candidates"][0]["invite_status"] == "failed"
        assert (await User.get(admin.id)).level1_key is None
        mail.assert_not_awaited()

    async def test_resend_invites_after_failure(self):
        user = await make_candidate()
        pid = await run_to_end([cand_input(user)], AsyncMock(return_value=False))
        assert (await pipeline_service.get_run(pid))["status"] == "done_with_errors"
        with patch("app.components.level1.invite_service.send_email", AsyncMock(return_value=True)):
            result = await pipeline_service.resend_invites(pid)
        assert result == {"invited": 1, "failed": 0}
        assert (await pipeline_service.get_run(pid))["status"] == "done"


class TestAddCandidates:
    async def test_adds_to_same_assessment(self):
        first = await make_candidate()
        pid = await run_to_end([cand_input(first)], AsyncMock(return_value=True))
        before = await pipeline_service.get_run(pid)
        late = await make_candidate("late@example.com", "Late Comer")
        mail = AsyncMock(return_value=True)
        with patch("app.components.level1.agents.analysis_agent.chat_json", AsyncMock(return_value=ANALYSIS)) as llm, \
             patch("app.components.level1.invite_service.send_email", mail):
            result = await pipeline_service.add_candidates(pid, [cand_input(late), cand_input(first)])
        assert result == {"invited": 1, "failed": 0}
        assert llm.await_count == 1  # only the new candidate analyzed; first is skipped as duplicate
        after = await pipeline_service.get_run(pid)
        assert after["assessment_id"] == before["assessment_id"] and after["share_link"] == before["share_link"]
        assert len(after["candidates"]) == 2
        assert await l1db.get_db()[l1db.QUESTIONS].count_documents({}) == 20
        share = await l1db.get_db()[l1db.SHARES].find_one({})
        assert set(share["restricted_emails"]) == {first.email, late.email}
        body = mail.await_args.args[2]
        assert (await User.get(late.id)).level1_key in body

    async def test_no_assessment_yet_raises_value_error(self):
        user = await make_candidate()
        db = l1db.get_db()
        res = await db[l1db.PIPELINES].insert_one({"hiring_jd_id": "jd1", "assessment_id": None, "jd_text": "x", "steps": []})
        with pytest.raises(ValueError):
            await pipeline_service.add_candidates(str(res.inserted_id), [cand_input(user)])

    async def test_unknown_run_404(self):
        with pytest.raises(HTTPException) as exc:
            await pipeline_service.add_candidates("64b0c0ffee0c0ffee0c0ffee", [])
        assert exc.value.status_code == 404
