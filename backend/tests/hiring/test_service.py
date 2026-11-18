"""Hiring orchestration: Level 1 result gate (above 75%), Level 2 promotion, batching."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app._core.settings import settings
from app.components.auth import service as auth_service
from app.components.common.schemas import Role
from app.components.hiring import service
from app.components.hiring.models import HiringCandidate
from app.components.level1.db import get_db
from app.components.sourcing.models import SourcedProfile
from tests.sourcing.helpers import make_ready_jd, make_user


async def _setup(pct: float, status: str = "completed"):
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    cand = await make_user("asha@example.com", Role.CANDIDATE, "Asha")
    await auth_service.issue_level1_key(cand)
    profile = SourcedProfile(
        sourcing_jd_id=str(jd.id), run_id="r1", source_link="https://x/1", name="Asha", email=cand.email,
        status="selected", candidate_user_id=str(cand.id),
    )
    await profile.insert()
    hc = await service.ensure_candidate(profile)
    db = get_db()
    assessment_id = ObjectId()
    # pipelines store the assessment id as text; submissions keep the ObjectId (real shapes)
    await db.l1_pipelines.insert_one({"assessment_id": str(assessment_id), "hiring_jd_id": str(jd.id)})
    sub = await db.l1_submissions.insert_one(
        {"assessment_id": assessment_id, "candidate_id": cand.id, "status": status, "percentage": pct,
         "rounds_data": []}
    )
    return hc, cand, str(sub.inserted_id)


@pytest.fixture(autouse=True)
def _no_real_email_or_report():
    with patch.object(service, "get_email_client", return_value=None), patch(
        "app.components.level1.report_service.build_report_html", return_value="<p>report</p>"
    ):
        yield


@pytest.mark.parametrize("pct,expect_promote", [(76.0, True), (100.0, True), (75.0, False), (40.0, False)])
async def test_pass_mark_is_strictly_above_75(pct, expect_promote):
    hc, cand, sid = await _setup(pct)
    promote = AsyncMock(return_value={"interview_id": "i1"})
    with patch.object(service, "promote_to_level2", promote):
        await service.on_level1_final(sid)
    assert promote.called is expect_promote
    fresh = await HiringCandidate.get(hc.id)
    assert fresh.level1_status == ("passed" if expect_promote else "failed")
    assert fresh.level1_percentage == pct
    assert fresh.level1_report_sent is True


async def test_level1_key_expired_on_final_and_terminated_never_passes():
    hc, cand, sid = await _setup(95.0, status="terminated")
    with patch.object(service, "promote_to_level2", AsyncMock()) as promote:
        await service.on_level1_final(sid)
    assert not promote.called
    assert (await HiringCandidate.get(hc.id)).level1_status == "terminated"
    from app.components.auth.models import User

    user = await User.get(cand.id)
    assert auth_service._is_expired(user.level1_key_expires_at)


async def test_final_hook_emails_once_and_retries_failed_promotion():
    hc, cand, sid = await _setup(90.0)
    emails = []

    async def email(h, *args):
        emails.append(1)
        h.level1_report_sent = True  # what the real sender records
        await h.save()

    attempts = []

    async def promote(h):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("LLM down")
        h = await HiringCandidate.get(h.id)
        h.level2_interview_id = "i1"
        await h.save()

    with patch.object(service, "promote_to_level2", promote), patch.object(service, "_email_level1_result", email):
        await service.on_level1_final(sid)   # promotion fails
        await service.on_level1_final(sid)   # retried, succeeds
        await service.on_level1_final(sid)   # fully handled: no-op
    assert len(attempts) == 2
    assert len(emails) == 1


async def test_sync_level1_starts_run_then_adds_late_candidates():
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    pipeline = MagicMock()
    pipeline.start_run = AsyncMock(return_value="pipe1")
    pipeline.add_candidates = AsyncMock(return_value={"invited": 1, "failed": 0})

    async def promoted(email):
        c = await make_user(email, Role.CANDIDATE, email)
        p = SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source_link=f"https://x/{email}", name=email,
                           email=email, status="selected", candidate_user_id=str(c.id))
        await p.insert()
        await service.ensure_candidate(p)

    with patch("app.components.level1.pipeline_service.start_run", pipeline.start_run), patch(
        "app.components.level1.pipeline_service.add_candidates", pipeline.add_candidates
    ):
        await promoted("a@x.com")
        await promoted("b@x.com")
        await service.sync_level1(jd_id)
        assert pipeline.start_run.call_count == 1
        assert len(pipeline.start_run.call_args.kwargs["candidates"]) == 2
        await promoted("c@x.com")
        await service.sync_level1(jd_id)
        assert pipeline.start_run.call_count == 1
        assert pipeline.add_candidates.call_count == 1
        await service.sync_level1(jd_id)  # nothing waiting -> no extra calls
        assert pipeline.add_candidates.call_count == 1


async def test_auto_select_only_profiles_with_contact_details(monkeypatch):
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    for i, email in enumerate(["has@x.com", ""]):
        await SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source_link=f"https://x/{i}", name=f"P{i}",
                             email=email, status="shortlisted").insert()
    selected = []

    async def fake_set_status(pid, status, note, user):
        selected.append(pid)

    monkeypatch.setattr(service.sourcing_service, "set_status", fake_set_status)
    await service._auto_select(jd, jd_id)
    assert len(selected) == 1
    assert settings.LEVEL1_PASS_PERCENT == 75


async def test_flow_record_creation_is_race_safe():
    import asyncio

    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    flows = await asyncio.gather(*(service._flow(str(jd.id)) for _ in range(6)))
    assert len({str(f.id) for f in flows}) == 1
