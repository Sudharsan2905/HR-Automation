"""GET /sourcing/profiles/{id}: one candidate's complete data for the detail view."""
import pytest
from fastapi import HTTPException

from app.components.common.schemas import Role
from app.components.sourcing import service
from app.components.sourcing.models import SourcedProfile, StatusEvent

from tests.sourcing.helpers import make_ready_jd, make_user

SCREENING = {
    "source_link": "https://resdex.naukri.com/p/1",
    "mandatory": [
        {"skill": "Python", "match": "present", "related_skill": "", "strength": "excellent", "evidence": "6 yrs Python"},
        {"skill": "Django", "match": "related", "related_skill": "Flask", "strength": "strong", "evidence": "Flask APIs"},
    ],
    "preferred": [{"skill": "AWS", "present": True, "evidence": "Lambda"}],
    "match_reasons": ["Strong Python"],
}


async def _profile(jd, user, **kw):
    p = SourcedProfile(
        sourcing_jd_id=str(jd.id), run_id="r1", source_link="https://resdex.naukri.com/p/1", name="Asha",
        headline="Backend dev", skills=["Python", "Flask"], total_experience="5 Years 2 Months",
        experiences=[{"company": "Acme", "title": "Dev", "duration": "2021 - Present", "is_current": True}],
        education=[{"degree": "B.E.", "institute": "Anna University", "year": "2019"}],
        current_ctc="12 Lacs", current_ctc_lacs=12, screening=SCREENING, score=78, status="shortlisted",
        status_history=[StatusEvent(status="shortlisted", by="system"),
                        StatusEvent(status="on_hold", by=str(user.id), note="call next week")],
        **kw,
    )
    await p.insert()
    return p


async def test_detail_has_full_data_findings_and_named_history():
    user = await make_user(name="Priya R")
    jd = await make_ready_jd(user)
    p = await _profile(jd, user)

    d = await service.get_profile(str(p.id), user)

    assert d["experiences"][0]["company"] == "Acme"
    assert d["education"][0]["institute"] == "Anna University"
    assert d["total_experience"] == "5 Years 2 Months" and d["current_ctc"] == "12 Lacs"
    assert [f["skill"] for f in d["mandatory_findings"]] == ["Python", "Django"]
    assert d["mandatory_findings"][1]["related_skill"] == "Flask"
    assert d["preferred_findings"][0]["skill"] == "AWS"
    assert [h["by_name"] for h in d["status_history"]] == ["SkillMate", "Priya R"]
    assert d["status_history"][1]["note"] == "call next week"
    assert d["jd_title"] == "Python Dev"


async def test_unscreened_profile_has_empty_findings():
    user = await make_user()
    jd = await make_ready_jd(user)
    p = await _profile(jd, user)
    p.screening = None
    await p.save()
    d = await service.get_profile(str(p.id), user)
    assert d["mandatory_findings"] == [] and d["preferred_findings"] == []


async def test_admin_can_view_other_recruiter_cannot():
    owner = await make_user()
    admin = await make_user(email="admin@softsuave.com", role=Role.SUPER_ADMIN, name="Admin")
    other = await make_user(email="other@softsuave.com")
    jd = await make_ready_jd(owner)
    p = await _profile(jd, owner)
    assert (await service.get_profile(str(p.id), admin))["name"] == "Asha"
    with pytest.raises(HTTPException):
        await service.get_profile(str(p.id), other)
