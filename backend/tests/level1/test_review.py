"""Admin review: list/detail with essay expectations, re-access with archive, terminate, complete."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.components.auth.models import User
from app.components.level1 import assessment_service, candidate_service, scoring_tasks, version_service
from app.components.level1 import db as l1db
from tests.level1.conftest import build_exam, make_admin, make_candidate


@pytest.fixture
async def started():
    user = await make_candidate()
    built = await build_exam([user.email])
    sub = await candidate_service.start_assessment(l1db.get_db(), built["share_link"], str(user.id))
    return user, built, sub


async def test_list_submissions_has_candidate_info(started):
    user, built, sub = started
    out = await assessment_service.get_submissions(l1db.get_db(), built["assessment_id"], None, "created_at", "desc", 1, 20)
    row = out["submissions"][0]
    assert row["candidate_name"] == "Asha Rao" and row["candidate_email"] == user.email
    assert row["status"] == "in_progress" and "rounds_data" not in row
    assert out["pagination"]["total"] == 1
    hit = await assessment_service.get_submissions(l1db.get_db(), built["assessment_id"], "asha", "created_at", "desc", 1, 20)
    miss = await assessment_service.get_submissions(l1db.get_db(), built["assessment_id"], "zzz", "created_at", "desc", 1, 20)
    assert hit["pagination"]["total"] == 1 and miss["pagination"]["total"] == 0


async def test_detail_includes_essay_expected_answer_and_feedback(started):
    user, built, sub = started
    db = l1db.get_db()
    stored = await db[l1db.SUBMISSIONS].find_one({})
    essay = next(q for q in stored["rounds_data"][0]["questions"] if q["type"] == "essay")
    await db[l1db.SUBMISSIONS].update_one({}, {"$set": {
        f"rounds_data.0.answers.{essay['id']}": "my essay",
        f"rounds_data.0.question_results.{essay['id']}": {"is_correct": True, "feedback": "Covers the key points"}}})
    await candidate_service.save_screenshot(db, sub["id"], str(user.id), b"x")
    await candidate_service.flag_malpractice(db, sub["id"], str(user.id), "tab_switch")
    detail = await assessment_service.get_submission_detail(db, built["assessment_id"], sub["id"])
    q = next(q for q in detail["rounds"][0]["questions"] if q["id"] == essay["id"])
    assert q["correct_answer"].startswith("A complete model answer") and q["feedback"] == "Covers the key points"
    assert q["candidate_answer"] == "my essay" and q["is_correct"] is True
    mcq = next(q for q in detail["rounds"][0]["questions"] if q["type"] == "mcq_single")
    assert len(mcq["correct_option_ids"]) == 1 and any(o["is_correct"] for o in mcq["options"])
    assert detail["candidate"]["email"] == user.email
    assert detail["malpractice_events"][0]["type"] == "tab_switch"
    assert detail["screenshots"][0]["url"].startswith("/api/level1/assessments/")


async def test_terminate_and_complete_only_for_live_sessions(started):
    _, built, sub = started
    db = l1db.get_db()
    current = await assessment_service.terminate_submission(db, built["assessment_id"], sub["id"], "cheating")
    assert current == 1
    assert (await db[l1db.SUBMISSIONS].find_one({}))["status"] == "terminated"
    for fn in (lambda: assessment_service.complete_submission(db, built["assessment_id"], sub["id"]),
               lambda: assessment_service.terminate_submission(db, built["assessment_id"], sub["id"], "x")):
        with pytest.raises(HTTPException) as exc:
            await fn()
        assert exc.value.status_code == 403


async def test_force_complete_sets_completed(started):
    _, built, sub = started
    await assessment_service.complete_submission(l1db.get_db(), built["assessment_id"], sub["id"])
    assert (await l1db.get_db()[l1db.SUBMISSIONS].find_one({}))["status"] == "completed"


async def test_reaccess_archives_and_issues_new_key(started):
    user, built, sub = started
    db = l1db.get_db()
    admin = await make_admin()
    with pytest.raises(HTTPException):  # still in progress
        await assessment_service.grant_reaccess(db, built["assessment_id"], sub["id"], str(admin.id), "r", "other")
    await assessment_service.terminate_submission(db, built["assessment_id"], sub["id"], "net")
    with patch("app.components.level1.mailer.get_email_client", return_value=None):
        key = await assessment_service.grant_reaccess(db, built["assessment_id"], sub["id"], str(admin.id), "network", "poor_network")
    refreshed = await User.get(user.id)
    assert refreshed.level1_key == key
    stored = await db[l1db.SUBMISSIONS].find_one({})
    assert stored["status"] == "pending" and stored["reaccess_count"] == 1 and stored["malpractice_count"] == 0
    versions = await version_service.get_versions_list(db, sub["id"])
    assert versions[0]["version"] == 1 and versions[0]["status"] == "terminated"
    detail = await version_service.get_version_detail(db, sub["id"], 1)
    assert len(detail["rounds"][0]["question_answers"]) == 20
    again = await candidate_service.start_assessment(db, built["share_link"], str(user.id))
    assert again["status"] == "in_progress"


async def test_reaccess_limit(started, monkeypatch):
    from app._core.settings import settings

    _, built, sub = started
    db = l1db.get_db()
    await assessment_service.complete_submission(db, built["assessment_id"], sub["id"])
    await db[l1db.SUBMISSIONS].update_one({}, {"$set": {"reaccess_count": settings.LEVEL1_MAX_REACCESS}})
    with pytest.raises(HTTPException) as exc:
        await assessment_service.grant_reaccess(db, built["assessment_id"], sub["id"], "a" * 24, "r", "other")
    assert exc.value.status_code == 403
