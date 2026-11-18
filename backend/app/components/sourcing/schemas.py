from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# --- LLM output schemas ---


class LLMSkill(BaseModel):
    name: str
    variants: list[str] = Field(default_factory=list)


class LLMRequirements(BaseModel):
    is_valid_jd: bool = True
    invalid_reason: str = ""
    role_title: str = ""
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    ctc_max_lacs: float | None = None
    locations: list[str] = Field(default_factory=list)
    mandatory_skills: list[LLMSkill] = Field(default_factory=list)
    preferred_skills: list[LLMSkill] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    avoid_companies: list[str] = Field(default_factory=list)


class LLMSearchPlan(BaseModel):
    primary_keywords: str = ""
    narrowed_keywords: str = ""


class LLMSkillFinding(BaseModel):
    skill: str
    match: Literal["present", "related", "absent"]
    related_skill: str = ""
    strength: Literal["none", "basic", "strong", "excellent"] = "none"
    evidence: str = ""


class LLMPreferredFinding(BaseModel):
    skill: str
    present: bool
    evidence: str = ""


class LLMScreenedProfile(BaseModel):
    source_link: str
    mandatory: list[LLMSkillFinding] = Field(default_factory=list)
    preferred: list[LLMPreferredFinding] = Field(default_factory=list)
    target_company_match: bool = False
    avoid_company_match: bool = False
    location_match: bool = False
    seniority_match: bool = False
    relevant_projects: bool = False
    match_reasons: list[str] = Field(default_factory=list)


class LLMScreenBatch(BaseModel):
    profiles: list[LLMScreenedProfile] = Field(default_factory=list)


# --- Request bodies ---


class ScrapedProfileIn(BaseModel):
    """A profile as the extension scraped it from ResDex (canonical shape)."""
    model_config = ConfigDict(extra="allow")

    name: str
    source_link: str = ""
    headline: str = ""
    location: str = ""
    skills: list[str] = Field(default_factory=list)
    experiences: list[dict] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)
    total_experience: str = ""
    experience_years: float | None = None
    current_ctc: str = ""
    current_ctc_lacs: float | None = None
    email: str = ""
    phone: str = ""


class ProfilesIn(BaseModel):
    profiles: list[ScrapedProfileIn] = Field(default_factory=list, max_length=400)
    ended: bool = False                 # ResDex had no further result pages
    pages_crawled: int | None = None    # ignored (older extension builds); SkillMate counts pages
    source_url: str = ""                # the ResDex page the extension scraped


class RunFailIn(BaseModel):
    reason: Literal["not_logged_in", "captcha", "cancelled", "error"]
    detail: str = ""


class StatusUpdateIn(BaseModel):
    status: Literal["selected", "rejected", "on_hold"]
    note: str = ""


class ContactIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
