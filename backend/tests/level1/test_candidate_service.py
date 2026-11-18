"""Candidate exam flow: access restriction, answers, finishing, strikes, screenshots, hold/resume."""

from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app._core.settings import settings
from app.components.auth.models import User
from app.components.level1 import assessment_service, candidate_service, scoring_tasks, storage
from app.components.level1 import db as l1db
from tests.level1.conftest import build_exam, make_admin, make_candidate


@pytest.fixture
async def exam():
    user = await make_candidate()
    built = await build_exam([user.email])
    return user, built


async def start(user, built) -> dict:
    return await candidate_service.start_assessment(l1db.get_db(), built["share_link"], str(user.id))


async def test_assessment_info_hides_question_ids(exam):
    _, built = exam
    info = await candidate_service.get_candidate_assessment(l1db.get_db(), built["share_link"])
    assert info["rounds"][0]["question_count"] == 20 and "question_ids" not in info["rounds"][0]


async def test_unknown_share_link_404():
    with pytest.raises(HTTPException) as exc:
        await candidate_service.get_candidate_assessment(l1db.get_db(), "nope")
    assert exc.value.status_code == 404


async def test_start_creates_submission_without_answers_leak(exam):
    user, built = exam
    sub = await start(user, built)
    assert sub["status"] == "in_progress"
    rd = await candidate_service.get_current_round(l1db.get_db(), sub["id"], str(user.id))
    assert len(rd["round"]["questions"]) == 20 and rd["tab_monitoring"] is True
    for q in rd["round"]["questions"]:
        assert "correct_answer" not in q and all("is_correct" not in o for o in q["options"])
    again = await start(user, built)
    assert again["id"] == sub["id"]


async def test_uninvited_candidate_blocked(exam):
    _, built = exam
    other = await make_candidate("other@example.com", "Other")
    with pytest.raises(HTTPException) as exc:
        await candidate_service.start_assessment(l1db.get_db(), built["share_link"], str(other.id))
    assert exc.value.status_code == 403


async def test_start_links_pipeline_candidate(exam):
    user, built = exam
    db = l1db.get_db()
    pid = (await db[l1db.PIPELINES].insert_one({"assessment_id": built["assessment_id"]})).inserted_id
    await db[l1db.PIPELINE_CANDIDATES].insert_one({"pipeline_id": pid, "user_id": str(user.id), "submission_id": None})
    sub = await start(user, built)
    assert (await db[l1db.PIPELINE_CANDIDATES].find_one({}))["submission_id"] == sub["id"]


async def test_answer_persist_and_session_state(exam):
    user, built = exam
    db = l1db.get_db()
    sub = await start(user, built)
    rd = await candidate_service.get_current_round(db, sub["id"], str(user.id))
    qid = rd["round"]["questions"][0]["id"]
    assert (await candidate_service.submit_answer(db, sub["id"], str(user.id), qid, ["a"])).saved
    stored = await db[l1db.SUBMISSIONS].find_one({"_id": ObjectId(sub["id"])})
    assert stored["rounds_data"][0]["answers"][qid] == ["a"]
    state = await candidate_service.get_session_state(db, sub["id"], str(user.id))
    assert state.status == "in_progress" and state.current_round == 1


async def test_other_candidate_cannot_touch_submission(exam):
    user, built = exam
    sub = await start(user, built)
    other = await make_candidate("o2@example.com")
    with pytest.raises(HTTPException) as exc:
        await candidate_service.submit_answer(l1db.get_db(), sub["id"], str(other.id), "q", "x")
    assert exc.value.status_code == 404


async def test_finish_round_completes_and_expires_key(exam):
    user, built = exam
    from app.components.auth.service import issue_level1_key

    await issue_level1_key(user)
    sub = await start(user, built)
    out = await candidate_service.finish_round(l1db.get_db(), sub["id"], str(user.id))
    assert out == {"completed": True, "finished_round": 1}
    stored = await l1db.get_db()[l1db.SUBMISSIONS].find_one({})
    assert stored["status"] == "completed" and stored["completed_at"]
    refreshed = await User.get(user.id)
    from app.components.auth.service import _is_expired

    assert _is_expired(refreshed.level1_key_expires_at)
    with pytest.raises(HTTPException):
        await candidate_service.start_assessment(l1db.get_db(), built["share_link"], str(user.id))


async def test_three_strikes_terminate(exam):
    user, built = exam
    db = l1db.get_db()
    sub = await start(user, built)
    results = [await candidate_service.flag_malpractice(db, sub["id"], str(user.id), "tab_switch") for _ in range(settings.LEVEL1_MAX_MALPRACTICE)]
    assert [r.malpractice_count for r in results] == [1, 2, 3]
    assert results[-1].is_terminal and not results[0].is_terminal
    stored = await db[l1db.SUBMISSIONS].find_one({})
    assert stored["status"] == "malpractice" and len(stored["malpractice_events"]) == 3


async def test_gated_event_ignored_when_monitoring_disabled(exam):
    user, built = exam
    db = l1db.get_db()
    sub = await start(user, built)
    await db[l1db.SUBMISSIONS].update_one({}, {"$set": {"monitoring_details.video_monitoring": False}})
    res = await candidate_service.flag_malpractice(db, sub["id"], str(user.id), "face_absence")
    assert res.malpractice_count == 0


async def test_screenshot_and_evidence_on_disk_served_to_admin(exam):
    user, built = exam
    db = l1db.get_db()
    sub = await start(user, built)
    await candidate_service.save_screenshot(db, sub["id"], str(user.id), b"jpegbytes")
    await candidate_service.flag_malpractice(db, sub["id"], str(user.id), "tab_switch", {"screen_image": (b"evidence", "image/jpeg")})
    stored = await db[l1db.SUBMISSIONS].find_one({})
    key = stored["screenshots"][0]["key"]
    assert (await storage.get_bytes(key))[0] == b"jpegbytes"
    content, _ = await assessment_service.get_media(db, built["assessment_id"], sub["id"], key)
    assert content == b"jpegbytes"
    ev_key = stored["malpractice_events"][0]["screen_image_key"]
    assert (await assessment_service.get_media(db, built["assessment_id"], sub["id"], ev_key))[0] == b"evidence"
    with pytest.raises(HTTPException):
        await assessment_service.get_media(db, built["assessment_id"], sub["id"], "../../etc/passwd")


async def test_storage_rejects_path_traversal():
    with pytest.raises(HTTPException):
        await storage.get_bytes("../outside")


async def test_hold_and_resume(exam):
    user, built = exam
    db = l1db.get_db()
    sub = await start(user, built)
    await candidate_service.put_session_on_hold(db, sub["id"])
    assert (await db[l1db.SUBMISSIONS].find_one({}))["status"] == "on_hold"
    again = await start(user, built)
    assert again["status"] == "on_hold"
    admin = await make_admin()
    await assessment_service.resume_interview(db, built["assessment_id"], sub["id"], str(admin.id))
    assert (await db[l1db.SUBMISSIONS].find_one({}))["status"] == "in_progress"
    with pytest.raises(HTTPException):
        await assessment_service.resume_interview(db, built["assessment_id"], sub["id"], str(admin.id))


async def test_submission_status_none_before_start(exam):
    user, built = exam
    db = l1db.get_db()
    assert await candidate_service.get_submission_status(db, built["share_link"], str(user.id)) is None
    sub = await start(user, built)
    status = await candidate_service.get_submission_status(db, built["share_link"], str(user.id))
    assert status.submission_id == sub["id"]
