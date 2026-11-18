from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile

from tests.sourcing.helpers import make_ready_jd, make_user

STAFF_ERROR = "This email belongs to a panel member or admin and cannot be used as a candidate"


async def _shortlisted(jd, **kw) -> SourcedProfile:
    p = SourcedProfile(sourcing_jd_id=str(jd.id), run_id="r", source_link="https://resdex/p/1",
                       name="Asha Kumar", status="shortlisted", score=80, **kw)
    await p.insert()
    return p


async def test_select_without_email_needs_contact():
    user = await make_user()
    p = await _shortlisted(await make_ready_jd(user))
    out = await service.set_status(str(p.id), "selected", "", user)
    assert out["needs_contact"] is True
    assert out["profile"]["status"] == "selected"
    assert out["profile"]["candidate_user_id"] is None


async def test_contact_then_promote_creates_candidate():
    user = await make_user()
    p = await _shortlisted(await make_ready_jd(user))
    await service.set_status(str(p.id), "selected", "", user)
    out = await service.save_contact(str(p.id), "Asha@Mail.com", "9876543210", user)
    assert out["candidate_error"] is None
    cand = await User.find_one(User.email == "asha@mail.com")
    assert cand.role == Role.CANDIDATE
    assert cand.full_name == "Asha Kumar"
    assert cand.created_by == str(user.id)
    assert out["profile"]["candidate_user_id"] == str(cand.id)
    assert out["profile"]["phone"] == "9876543210"


async def test_select_with_email_promotes_immediately():
    user = await make_user()
    p = await _shortlisted(await make_ready_jd(user), email="ravi@mail.com")
    out = await service.set_status(str(p.id), "selected", "", user)
    assert out["needs_contact"] is False
    assert out["profile"]["candidate_user_id"] is not None


async def test_select_with_existing_candidate_links_without_changing_owner():
    user = await make_user()
    existing = User(email="asha@mail.com", role=Role.CANDIDATE, full_name="Asha K", created_by="other-recruiter")
    await existing.insert()
    p = await _shortlisted(await make_ready_jd(user), email="asha@mail.com")
    out = await service.set_status(str(p.id), "selected", "", user)
    assert out["profile"]["candidate_user_id"] == str(existing.id)
    assert (await User.get(existing.id)).created_by == "other-recruiter"


async def test_select_with_staff_email_is_refused():
    user = await make_user()
    await make_user(email="panel@softsuave.com")
    p = await _shortlisted(await make_ready_jd(user))
    await service.set_status(str(p.id), "selected", "", user)
    out = await service.save_contact(str(p.id), "panel@softsuave.com", None, user)
    assert out["candidate_error"] == STAFF_ERROR
    assert out["profile"]["status"] == "selected"
    assert out["profile"]["candidate_user_id"] is None
    assert await User.find(User.email == "panel@softsuave.com").count() == 1


async def test_reject_and_on_hold_record_history():
    user = await make_user()
    p = await _shortlisted(await make_ready_jd(user))
    await service.set_status(str(p.id), "on_hold", "", user)
    out = await service.set_status(str(p.id), "rejected", "no notice period", user)
    hist = out["profile"]["status_history"]
    assert [h["status"] for h in hist[-2:]] == ["on_hold", "rejected"]
    assert hist[-1]["note"] == "no notice period"
    assert hist[-1]["by"] == str(user.id)


async def test_list_profiles_shows_other_owner_of_candidate():
    user = await make_user()
    other = await make_user(email="other@softsuave.com", name="Priya")
    existing = User(email="asha@mail.com", role=Role.CANDIDATE, full_name="Asha", created_by=str(other.id))
    await existing.insert()
    jd = await make_ready_jd(user)
    p = await _shortlisted(jd, email="asha@mail.com")
    await service.set_status(str(p.id), "selected", "", user)
    rows = await service.list_profiles(str(jd.id), user, "selected")
    assert rows[0]["existing_candidate_owner"] == "Priya"
