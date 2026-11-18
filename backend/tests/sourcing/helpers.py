from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.sourcing.models import SkillSpec, SourcingJd, SourcingRequirements, SourcingSearchPlan
from app.components.sourcing.schemas import (
    LLMScreenBatch,
    LLMScreenedProfile,
    LLMSkillFinding,
    ScrapedProfileIn,
)

JD_TEXT = "We are hiring a Python developer with Django experience, 3-6 years, Chennai. " * 3


async def make_user(email="rec@softsuave.com", role=Role.INTERVIEWER, name="Recruiter") -> User:
    u = User(email=email, role=role, full_name=name)
    await u.insert()
    return u


async def make_ready_jd(user: User, **overrides) -> SourcingJd:
    jd = SourcingJd(
        created_by=str(user.id),
        title="Python Dev",
        jd_text=JD_TEXT,
        requirements=SourcingRequirements(
            mandatory_skills=[SkillSpec(name="Python"), SkillSpec(name="Django")],
            experience_min_years=3, experience_max_years=6,
        ),
        search_plan=SourcingSearchPlan(primary_keywords="Python AND Django", narrowed_keywords="Python AND Django AND AWS"),
        requirements_version=1,
        analysis_status="done",
    )
    for k, v in overrides.items():
        setattr(jd, k, v)
    await jd.insert()
    return jd


def scraped(i: int, **kw) -> ScrapedProfileIn:
    data = dict(name=f"Cand {i}", source_link=f"https://resdex.naukri.com/p/{i}", skills=["Python", "Django"],
                experience_years=4, experiences=[{"company": f"Co{i}", "title": "Dev", "is_current": True}])
    data.update(kw)
    return ScrapedProfileIn(**data)


def all_present_batch(links: list[str], strength="basic") -> LLMScreenBatch:
    return LLMScreenBatch(profiles=[
        LLMScreenedProfile(
            source_link=link,
            mandatory=[LLMSkillFinding(skill="Python", match="present", strength=strength),
                       LLMSkillFinding(skill="Django", match="present", strength=strength)],
            match_reasons=["Python and Django listed"],
        )
        for link in links
    ])
