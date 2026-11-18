from app.components.sourcing.models import SkillSpec, SourcingRequirements
from app.components.sourcing.schemas import LLMPreferredFinding, LLMScreenedProfile, LLMSkillFinding
from app.components.sourcing.scoring import compute_score, related_notes

REQ = SourcingRequirements(
    mandatory_skills=[SkillSpec(name="Python"), SkillSpec(name="Django")],
    preferred_skills=[SkillSpec(name="AWS")],
    experience_min_years=3,
    experience_max_years=6,
    ctc_max_lacs=15,
)


def screen(**kw) -> LLMScreenedProfile:
    base = dict(
        source_link="l",
        mandatory=[
            LLMSkillFinding(skill="Python", match="present", strength="basic"),
            LLMSkillFinding(skill="Django", match="present", strength="basic"),
        ],
        preferred=[],
    )
    base.update(kw)
    return LLMScreenedProfile(**base)


def test_absent_mandatory_rejects():
    s = screen(mandatory=[LLMSkillFinding(skill="Python", match="present"),
                          LLMSkillFinding(skill="Django", match="absent")])
    score, b = compute_score(s, 4, 10, REQ)
    assert score == 0
    assert b["rejected_reason"] == "missing mandatory: Django"


def test_related_mandatory_costs_ten():
    s = screen(mandatory=[LLMSkillFinding(skill="Python", match="present"),
                          LLMSkillFinding(skill="Django", match="related", related_skill="Flask")])
    assert compute_score(s, 4, 10, REQ)[0] == 50
    assert related_notes(s) == ["Django not listed — related: Flask"]


def test_experience_and_ctc_rejections_only_when_known():
    assert compute_score(screen(), 2, 10, REQ)[0] == 0
    assert compute_score(screen(), 7, 10, REQ)[0] == 0
    assert compute_score(screen(), 4, 16, REQ)[0] == 0
    assert compute_score(screen(), None, None, REQ)[0] == 60


def test_avoid_company_rejects():
    score, b = compute_score(screen(avoid_company_match=True), 4, 10, REQ)
    assert score == 0
    assert b["rejected_reason"] == "avoid-list company"


def test_strength_bonuses_do_not_stack():
    first_excellent = screen(mandatory=[LLMSkillFinding(skill="Python", match="present", strength="excellent"),
                                        LLMSkillFinding(skill="Django", match="present", strength="strong")])
    assert compute_score(first_excellent, 4, 10, REQ)[0] == 85
    two_strong = screen(mandatory=[LLMSkillFinding(skill="Python", match="present", strength="strong"),
                                   LLMSkillFinding(skill="Django", match="present", strength="strong")])
    assert compute_score(two_strong, 4, 10, REQ)[0] == 75


def test_bonuses_and_cap():
    s = screen(
        mandatory=[LLMSkillFinding(skill="Python", match="present", strength="excellent"),
                   LLMSkillFinding(skill="Django", match="present", strength="excellent")],
        preferred=[LLMPreferredFinding(skill="AWS", present=True)],
        target_company_match=True, relevant_projects=True, location_match=True, seniority_match=True,
    )
    score, b = compute_score(s, 4, 10, REQ)
    assert score == 100
    assert b["total"] == 100  # 60+25+7+5+5+3+5 = 110, capped
