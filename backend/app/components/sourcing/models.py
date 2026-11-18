from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SkillSpec(BaseModel):
    """A skill and its genuine spelling variants (e.g. Node.js → Node, NodeJS)."""
    name: str
    variants: list[str] = Field(default_factory=list)


class SourcingRequirements(BaseModel):
    """JD Analyst output: the hiring requirements used for search and screening."""
    role_title: str = ""
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    ctc_max_lacs: float | None = None
    locations: list[str] = Field(default_factory=list)
    mandatory_skills: list[SkillSpec] = Field(default_factory=list)
    preferred_skills: list[SkillSpec] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    avoid_companies: list[str] = Field(default_factory=list)


class SourcingSearchPlan(BaseModel):
    """Search Strategist output: what the extension types into ResDex."""
    primary_keywords: str = ""
    narrowed_keywords: str = ""
    use_narrowed: bool = False
    experience_min: float | None = None
    experience_max: float | None = None
    locations: list[str] = Field(default_factory=list)
    ctc_max_lacs: float | None = None


class StatusEvent(BaseModel):
    status: str
    by: str
    at: datetime = Field(default_factory=_now)
    note: str = ""


class SourcingJd(Document):
    """A JD that candidates are sourced for. Separate from JD Analyze."""
    created_by: str
    title: str
    jd_text: str
    jd_filename: str | None = None
    requirements: SourcingRequirements = Field(default_factory=SourcingRequirements)
    search_plan: SourcingSearchPlan = Field(default_factory=SourcingSearchPlan)
    requirements_version: int = 0
    analysis_status: str = "generating"  # generating | done | failed
    analysis_error: str | None = None
    next_page: int = 1
    pool_exhausted: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "sourcing_jds"
        indexes = ["created_by"]


class SourcingRun(Document):
    """One "Source from Naukri" click."""
    sourcing_jd_id: str
    run_no: int
    clicked_by: str
    mode: str  # pool | scrape
    keywords_used: str = ""
    pages_from: int | None = None
    pages_to: int | None = None
    pages_crawled: int | None = None
    results_ended: bool = False
    source_url: str = ""
    profiles_received: int = 0
    profiles_new: int = 0
    profiles_shortlisted: int = 0
    status: str = "pending"  # pending | scraping | screening | done | failed | cancelled
    phase: str = "hunting"   # hunting (looking for 5) | prefetch (reading extra pages into the pool)
    prefetch_left: int = 0
    next_action: str | None = None  # "next_page" while SkillMate is waiting for the extension's next page
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime | None = None  # last activity; a run idle past the timeout is expired
    finished_at: datetime | None = None

    class Settings:
        name = "sourcing_runs"
        indexes = ["sourcing_jd_id"]


class SourcedProfile(Document):
    """A Naukri profile found for a sourcing JD."""
    sourcing_jd_id: str
    run_id: str
    shortlisted_in_run_id: str | None = None
    source: str = "Naukri"
    source_link: str
    name: str
    headline: str = ""
    location: str = ""
    current_company: str = ""
    current_title: str = ""
    skills: list[str] = Field(default_factory=list)
    experiences: list[dict] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)
    total_experience: str = ""
    experience_years: float | None = None
    current_ctc: str = ""
    current_ctc_lacs: float | None = None
    raw: dict = Field(default_factory=dict)
    email: str = ""
    phone: str = ""
    contact_revealed_at: datetime | None = None
    screening: dict | None = None
    screened_with_version: int | None = None
    score: int | None = None
    score_breakdown: dict = Field(default_factory=dict)
    match_reasons: list[str] = Field(default_factory=list)
    related_notes: list[str] = Field(default_factory=list)
    status: str = "pool"  # pool | shortlisted | selected | rejected | on_hold | below_threshold
    status_history: list[StatusEvent] = Field(default_factory=list)
    candidate_user_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "sourced_profiles"
        indexes = [
            IndexModel([("sourcing_jd_id", ASCENDING), ("source_link", ASCENDING)], unique=True),
            IndexModel([("sourcing_jd_id", ASCENDING), ("status", ASCENDING)]),
        ]
