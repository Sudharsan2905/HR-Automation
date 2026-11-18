import pytest

from app.components.sourcing import agents
from app.components.sourcing.models import SkillSpec, SourcedProfile, SourcingRequirements
from app.components.sourcing.schemas import (
    LLMRequirements,
    LLMScreenBatch,
    LLMScreenedProfile,
    LLMSearchPlan,
    LLMSkill,
    LLMSkillFinding,
)


@pytest.fixture(autouse=True)
def patch_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("app.components.sourcing.agents.get_llm_client", lambda: fake_llm)


async def test_analyze_jd_rejects_non_jd(fake_llm):
    fake_llm.queue(LLMRequirements(is_valid_jd=False, invalid_reason="This is a recipe"))
    with pytest.raises(ValueError, match="recipe"):
        await agents.analyze_jd("2 eggs, flour")


async def test_analyze_jd_returns_requirements_and_trims(fake_llm):
    fake_llm.queue(LLMRequirements(
        role_title="Backend Dev",
        mandatory_skills=[LLMSkill(name=f"S{i}", variants=[f"v{j}" for j in range(9)]) for i in range(12)],
        experience_min_years=3,
    ))
    req = await agents.analyze_jd("Backend developer with Python ...")
    assert req.role_title == "Backend Dev"
    assert req.experience_min_years == 3
    assert len(req.mandatory_skills) == 10
    assert len(req.mandatory_skills[0].variants) == 6
    assert "Backend developer with Python" in fake_llm.calls[0][0]


async def test_search_plan_copies_filters_from_requirements(fake_llm):
    fake_llm.queue(LLMSearchPlan(primary_keywords='Python AND ("Django" OR "DRF")', narrowed_keywords="x"))
    req = SourcingRequirements(experience_min_years=3, experience_max_years=6, locations=["Chennai"], ctc_max_lacs=15)
    plan = await agents.build_search_plan(req)
    assert plan.experience_min == 3 and plan.experience_max == 6
    assert plan.locations == ["Chennai"] and plan.ctc_max_lacs == 15
    assert plan.primary_keywords.startswith("Python AND")


async def test_screen_chunks_and_drops_foreign_links(fake_llm, monkeypatch):
    monkeypatch.setattr("app.components.sourcing.agents.settings.SOURCING_SCREEN_CHUNK", 2)
    profiles = [SourcedProfile(sourcing_jd_id="j", run_id="r", source_link=f"l{i}", name=f"P{i}") for i in range(3)]
    f = [LLMSkillFinding(skill="Python", match="present")]
    fake_llm.queue(LLMScreenBatch(profiles=[LLMScreenedProfile(source_link="l0", mandatory=f),
                                            LLMScreenedProfile(source_link="bogus", mandatory=f)]))
    fake_llm.queue(LLMScreenBatch(profiles=[LLMScreenedProfile(source_link="l2", mandatory=f)]))
    out = await agents.screen_profiles(SourcingRequirements(mandatory_skills=[SkillSpec(name="Python")]), profiles)
    assert set(out) == {"l0", "l2"}
    assert len(fake_llm.calls) == 2
