from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HiringFlow(Document):
    """One hiring journey per sourcing JD: links the Level 1 exam run."""
    sourcing_jd_id: str
    level1_pipeline_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "hiring_flows"
        indexes = [IndexModel([("sourcing_jd_id", ASCENDING)], unique=True)]


class HiringCandidate(Document):
    """A selected candidate's progress through Level 1 and Level 2."""
    sourcing_jd_id: str
    profile_id: str
    user_id: str
    name: str
    email: str
    level1_status: str = "not_started"  # not_started | invited | evaluating | passed | failed | terminated
    level1_submission_id: str | None = None
    level1_percentage: float | None = None
    level1_report_sent: bool = False
    level2_jd_interview_id: str | None = None
    level2_interview_id: str | None = None
    level2_due_date: datetime | None = None
    promoted_manually: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "hiring_candidates"
        indexes = [
            IndexModel([("sourcing_jd_id", ASCENDING), ("profile_id", ASCENDING)], unique=True),
            "user_id",
            "level1_submission_id",
        ]


class HiringEvent(Document):
    """Human-readable activity feed for a JD's flow."""
    sourcing_jd_id: str
    stage: str  # jd | sourcing | level1 | level2 | report
    level: str = "info"  # info | warn | error
    message: str
    ts: datetime = Field(default_factory=_now)

    class Settings:
        name = "hiring_events"
        indexes = [IndexModel([("sourcing_jd_id", ASCENDING), ("ts", ASCENDING)])]
