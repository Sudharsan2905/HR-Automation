from fastapi import APIRouter

from app._core.settings import settings
from app.components.common.enums import (
    BDEDomain,
    HRDomain,
    TechDomain,
    UmbrellaDomain,
)
from app.components.common.schemas import (
    ContributionStatus,
    DifficultyLevel,
    InterviewStatus,
    QuestionSetStatus,
    Role,
    UserStatus,
)

router = APIRouter(prefix="/discovery", tags=["Discovery"])


@router.get("/enums")
async def get_all_enums():
    """Expose all enum values for frontend discovery."""
    return {
        "roles": [e.value for e in Role],
        "user_statuses": [e.value for e in UserStatus],
        "difficulty_levels": [e.value for e in DifficultyLevel],
        "interview_statuses": [e.value for e in InterviewStatus],
        "question_set_statuses": [e.value for e in QuestionSetStatus],
        "contribution_statuses": [e.value for e in ContributionStatus],
        "umbrella_domains": [e.value for e in UmbrellaDomain],
        "tech_domains": [e.value for e in TechDomain],
        "bde_domains": [e.value for e in BDEDomain],
        "hr_domains": [e.value for e in HRDomain],
        "max_questions_per_set": settings.MAX_QUESTIONS_PER_SET,
    }
