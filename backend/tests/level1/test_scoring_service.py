"""Scoring: MCQ in code, batched essay LLM with retries, final hiring hook."""

from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from app._core.settings import settings
from app.components.level1 import db as l1db
from app.components.level1 import report_service, scoring_service, scoring_tasks
from app.components.level1.scoring_service import _parse_essay_results, _score_mcq


def test_mcq_single_and_multi():
    original = {"options": [{"id": "a", "text": "x", "is_correct": True}, {"id": "b", "text": "y", "is_correct": True},
                            {"id": "c", "text": "z", "is_correct": False}]}
    assert _score_mcq(original, ["a", "b"]) == (1, True)
    assert _score_mcq(original, ["a"]) == (0, False)
    assert _score_mcq(original, None) == (0, False)


def test_parse_tolerates_fences_and_wrapper():
    assert _parse_essay_results('```json\n[{"question_id":"1","is_correct":true}]\n```')[0]["question_id"] == "1"
    assert len(_parse_essay_results('{"results":[{"a":1},{"a":2}]}')) == 2


ESSAYS = [("q1", "Q one?", "model", "ans"), ("q2", "Q two?", "model", "ans")]


async def test_batch_without_api_key_is_unevaluated():
    out = await scoring_service._score_essays_batch(ESSAYS)
    assert all(r["is_correct"] is None for r in out.values())


async def test_batch_reasks_skipped_essays(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "k")
    llm = AsyncMock(side_effect=[{"q1": {"is_correct": True, "feedback": "ok"}}, {"q2": {"is_correct": False, "feedback": "no"}}])
    with patch.object(scoring_service, "_call_essay_llm", llm):
        out = await scoring_service._score_essays_batch(ESSAYS)
    assert out["q1"]["is_correct"] is True and out["q2"]["is_correct"] is False
    assert llm.await_count == 2 and len(llm.await_args.args[0]) == 1


async def test_batch_gives_up_after_two_attempts(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "k")
    with patch.object(scoring_service, "_call_essay_llm", AsyncMock(side_effect=RuntimeError("x"))):
        out = await scoring_service._score_essays_batch(ESSAYS)
    assert out["q1"]["feedback"] == "Scoring error" and out["q1"]["is_correct"] is None


def test_positional_fallback():
    results = [{"question_id": "renamed1", "is_correct": True}, {"question_id": "renamed2", "is_correct": False}]
    out = scoring_service._match_results(results, ["q1", "q2"])
    assert out["q1"]["is_correct"] is True and out["q2"]["is_correct"] is False


async def _submission(db, essays_answered=True) -> str:
    mcq = await db[l1db.QUESTIONS].insert_one({"question_text": "pick", "question_type": "mcq_single",
        "options": [{"id": "a", "text": "x", "is_correct": True}, {"id": "b", "text": "y", "is_correct": False}]})
    essay = await db[l1db.QUESTIONS].insert_one({"question_text": "explain", "question_type": "essay", "correct_answer": "model answer"})
    sub = await db[l1db.SUBMISSIONS].insert_one({
        "assessment_id": ObjectId(), "candidate_id": ObjectId(), "status": "completed", "score": 0, "percentage": 0.0,
        "rounds_data": [{"round_number": 1, "questions": [
            {"id": str(mcq.inserted_id), "type": "mcq_single", "text": "pick"},
            {"id": str(essay.inserted_id), "type": "essay", "text": "explain"}],
            "answers": {str(mcq.inserted_id): ["a"], str(essay.inserted_id): "my answer"}}]})
    return str(sub.inserted_id)


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(scoring_tasks, "_RETRY_DELAY_SECONDS", 0)


async def test_task_scores_and_calls_hook_when_all_evaluated(fast, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "k")
    db = l1db.get_db()
    sid = await _submission(db)
    qid = (await db[l1db.SUBMISSIONS].find_one({}))["rounds_data"][0]["questions"][1]["id"]
    hook = AsyncMock()
    with patch.object(scoring_service, "_call_essay_llm", AsyncMock(return_value={qid: {"is_correct": True, "feedback": "good"}})), \
         patch("app.components.hiring.service.on_level1_final", hook, create=True):
        await scoring_tasks.calculate_and_store_score(db, sid, 1)
    sub = await db[l1db.SUBMISSIONS].find_one({})
    assert sub["score"] == 2 and sub["percentage"] == 100.0
    assert report_service.unevaluated_count(sub) == 0
    hook.assert_awaited_once_with(sid)


async def test_task_retries_then_withholds_hook_when_unevaluated(fast):
    db = l1db.get_db()
    sid = await _submission(db)  # no api key -> essay stays unevaluated
    hook = AsyncMock()
    with patch("app.components.hiring.service.on_level1_final", hook, create=True), \
         patch("app.components.level1.scoring_tasks.score_round", wraps=scoring_service.score_round) as spy2:
        await scoring_tasks.calculate_and_store_score(db, sid, 1)
    assert spy2.call_count == 3
    hook.assert_not_awaited()
    assert report_service.unevaluated_count(await db[l1db.SUBMISSIONS].find_one({})) == 1


async def test_hook_failure_is_swallowed(fast, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "k")
    with patch("app.components.hiring.service.on_level1_final", AsyncMock(side_effect=RuntimeError("x")), create=True):
        await scoring_tasks.notify_final("abc")


def test_build_report_html():
    sub = {"score": 1, "percentage": 50, "status": "malpractice", "rounds_data": [
        {"questions": [{"id": "1", "text": "<b>Q</b>"}, {"id": "2", "text": "Q2"}],
         "question_results": {"1": {"is_correct": True, "feedback": "fine"}, "2": {"is_correct": False}}}]}
    html = report_service.build_report_html("Dev", "Asha", sub)
    assert "Asha" in html and "Correct" in html and "&lt;b&gt;" in html and "proctoring violation" in html
