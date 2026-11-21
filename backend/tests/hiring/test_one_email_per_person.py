"""The same person found on Naukri and on LinkedIn is invited to Level 1 once, not twice."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.components.common.schemas import Role
from app.components.hiring import service
from app.components.hiring.models import HiringCandidate, HiringEvent
from app.components.sourcing.models import SourcedProfile
from tests.sourcing.helpers import make_ready_jd, make_user


async def _promoted(jd_id: str, candidate, link: str, source: str, name: str) -> SourcedProfile:
    p = SourcedProfile(sourcing_jd_id=jd_id, run_id="r", source=source, source_link=link, name=name,
                       email=candidate.email, status="selected", candidate_user_id=str(candidate.id))
    await p.insert()
    return p


async def test_second_profile_with_the_same_email_reuses_the_first_hiring_row():
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    cand = await make_user("asha@example.com", Role.CANDIDATE, "Asha")
    naukri = await _promoted(jd_id, cand, "https://resdex.naukri.com/p/1", "Naukri", "Asha K")
    linkedin = await _promoted(jd_id, cand, "https://www.linkedin.com/in/asha", "LinkedIn", "Asha Kumar")

    first = await service.ensure_candidate(naukri)
    second = await service.ensure_candidate(linkedin)

    assert second.id == first.id
    assert await HiringCandidate.find(HiringCandidate.sourcing_jd_id == jd_id).count() == 1
    events = await HiringEvent.find(HiringEvent.sourcing_jd_id == jd_id).to_list()
    assert any("same email" in e.message and "LinkedIn" in e.message for e in events)


async def test_ensure_candidate_is_still_idempotent_for_one_profile():
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    cand = await make_user("asha@example.com", Role.CANDIDATE, "Asha")
    p = await _promoted(str(jd.id), cand, "https://resdex.naukri.com/p/1", "Naukri", "Asha")
    a = await service.ensure_candidate(p)
    b = await service.ensure_candidate(p)
    assert a.id == b.id


async def test_two_sources_one_invite_even_when_the_second_arrives_later():
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    cand = await make_user("asha@example.com", Role.CANDIDATE, "Asha")
    pipeline = MagicMock()
    pipeline.start_run = AsyncMock(return_value="pipe1")
    pipeline.add_candidates = AsyncMock(return_value={"invited": 1, "failed": 0})

    with patch("app.components.level1.pipeline_service.start_run", pipeline.start_run), patch(
        "app.components.level1.pipeline_service.add_candidates", pipeline.add_candidates
    ):
        await service.on_profile_promoted(await _promoted(jd_id, cand, "https://resdex.naukri.com/p/1", "Naukri", "Asha"))
        await service.sync_level1(jd_id)
        assert pipeline.start_run.call_count == 1
        assert [c["email"] for c in pipeline.start_run.call_args.kwargs["candidates"]] == ["asha@example.com"]

        # the LinkedIn copy of the same person is selected afterwards
        await service.on_profile_promoted(await _promoted(jd_id, cand, "https://www.linkedin.com/in/asha", "LinkedIn", "Asha"))
        await service.sync_level1(jd_id)
        assert pipeline.start_run.call_count == 1
        assert pipeline.add_candidates.call_count == 0      # no second invite


async def test_two_waiting_rows_for_one_email_are_invited_once():
    """Safety net: if two rows for one person ever exist at the same time, one invite goes out."""
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    cand = await make_user("asha@example.com", Role.CANDIDATE, "Asha")
    for i, link in enumerate(["https://resdex.naukri.com/p/1", "https://www.linkedin.com/in/asha"]):
        p = await _promoted(jd_id, cand, link, "Naukri" if i == 0 else "LinkedIn", "Asha")
        await HiringCandidate(sourcing_jd_id=jd_id, profile_id=str(p.id), user_id=str(cand.id), name="Asha",
                              email="Asha@Example.com").insert()
    pipeline = MagicMock()
    pipeline.start_run = AsyncMock(return_value="pipe1")

    with patch("app.components.level1.pipeline_service.start_run", pipeline.start_run):
        await service.sync_level1(jd_id)

    assert len(pipeline.start_run.call_args.kwargs["candidates"]) == 1
    assert await HiringCandidate.find(HiringCandidate.sourcing_jd_id == jd_id).count() == 1


async def test_full_flow_naukri_and_linkedin_copy_of_one_person_get_one_invite():
    """The real selection code, end to end: both copies shortlisted, both selected, the same email revealed
    for each (Naukri's contact reveal, LinkedIn's contact dialog) -> one candidate, one hiring row, one invite."""
    from app.components.auth.models import User
    from app.components.sourcing import service as sourcing

    recruiter = await make_user("rec@softsuave.com", Role.INTERVIEWER, "Recruiter")
    jd = await make_ready_jd(recruiter)
    jd_id = str(jd.id)
    naukri = SourcedProfile(sourcing_jd_id=jd_id, run_id="r1", source="Naukri", source_link="https://resdex.naukri.com/p/1",
                            name="Asha K", status="shortlisted", score=82)
    linkedin = SourcedProfile(sourcing_jd_id=jd_id, run_id="r2", source="LinkedIn",
                              source_link="https://www.linkedin.com/in/asha", name="Asha Kumar", status="shortlisted", score=60)
    await naukri.insert()
    await linkedin.insert()
    pipeline = MagicMock()
    pipeline.start_run = AsyncMock(return_value="pipe1")
    pipeline.add_candidates = AsyncMock(return_value={"invited": 1, "failed": 0})

    with patch("app.components.level1.pipeline_service.start_run", pipeline.start_run), patch(
        "app.components.level1.pipeline_service.add_candidates", pipeline.add_candidates
    ):
        # recruiter selects the Naukri copy and its contact is revealed
        out = await sourcing.set_status(str(naukri.id), "selected", "", recruiter)
        assert out["needs_contact"] is True
        await sourcing.save_contact(str(naukri.id), "Asha@Mail.com", "9876543210", recruiter)
        await service.sync_level1(jd_id)
        assert pipeline.start_run.call_count == 1

        # later the LinkedIn copy is selected; the connection's dialog shows the same email in another case
        out = await sourcing.set_status(str(linkedin.id), "selected", "", recruiter)
        assert out["needs_contact"] is True
        res = await sourcing.save_contact(str(linkedin.id), "ASHA@mail.com", None, recruiter)
        assert res["candidate_error"] is None
        await service.sync_level1(jd_id)

    assert pipeline.start_run.call_count == 1 and pipeline.add_candidates.call_count == 0   # no second invite
    assert await User.find(User.email == "asha@mail.com", User.role == Role.CANDIDATE).count() == 1
    rows = await HiringCandidate.find(HiringCandidate.sourcing_jd_id == jd_id).to_list()
    assert len(rows) == 1 and rows[0].level1_status == "invited"
    assert [c["email"] for c in pipeline.start_run.call_args.kwargs["candidates"]] == ["asha@mail.com"]
    # both profiles still point at the one candidate
    both = await SourcedProfile.find(SourcedProfile.sourcing_jd_id == jd_id).to_list()
    assert len({p.candidate_user_id for p in both}) == 1


async def test_a_waiting_row_for_an_already_invited_email_is_dropped_not_invited_again():
    admin = await make_user("admin@x.com", Role.SUPER_ADMIN, "Admin")
    jd = await make_ready_jd(admin)
    jd_id = str(jd.id)
    cand = await make_user("asha@example.com", Role.CANDIDATE, "Asha")
    first = await _promoted(jd_id, cand, "https://resdex.naukri.com/p/1", "Naukri", "Asha")
    await HiringCandidate(sourcing_jd_id=jd_id, profile_id=str(first.id), user_id=str(cand.id), name="Asha",
                          email="asha@example.com", level1_status="invited").insert()
    second = await _promoted(jd_id, cand, "https://www.linkedin.com/in/asha", "LinkedIn", "Asha")
    await HiringCandidate(sourcing_jd_id=jd_id, profile_id=str(second.id), user_id=str(cand.id), name="Asha",
                          email="Asha@Example.com").insert()   # e.g. created before the dedupe existed
    pipeline = MagicMock()
    pipeline.start_run = AsyncMock(return_value="pipe1")
    pipeline.add_candidates = AsyncMock(return_value={"invited": 1, "failed": 0})

    with patch("app.components.level1.pipeline_service.start_run", pipeline.start_run), patch(
        "app.components.level1.pipeline_service.add_candidates", pipeline.add_candidates
    ):
        assert await service.sync_level1(jd_id) is None

    assert pipeline.start_run.call_count == 0 and pipeline.add_candidates.call_count == 0
    rows = await HiringCandidate.find(HiringCandidate.sourcing_jd_id == jd_id).to_list()
    assert len(rows) == 1 and rows[0].level1_status == "invited"
