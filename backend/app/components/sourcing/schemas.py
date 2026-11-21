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
    # "unverified" is only meaningful for LinkedIn cards, which show a headline and a snippet but not the
    # full profile: the skill is not visible, yet the Boolean search already matched it on LinkedIn's side.
    match: Literal["present", "related", "absent", "unverified"]
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
    """A profile as an extension scraped it from ResDex or LinkedIn (canonical shape)."""
    model_config = ConfigDict(extra="allow")

    name: str
    source_link: str = ""
    headline: str = ""
    snippet: str = ""                   # LinkedIn: the text shown under a search result (matched keywords)
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


class ProfileStreamIn(BaseModel):
    """People of the page being read, sent as soon as the extension has them (usually one at a time)."""
    profiles: list[ScrapedProfileIn] = Field(default_factory=list, max_length=50)


class ProfilesIn(BaseModel):
    profiles: list[ScrapedProfileIn] = Field(default_factory=list, max_length=400)
    ended: bool = False                 # the source had no further result pages
    pages_crawled: int | None = None    # ignored (older extension builds); SkillMate counts pages
    source_url: str = ""                # the results page the extension scraped
    search_level: int | None = Field(None, ge=0, le=20)   # LinkedIn: the search step these pages came from
    # LinkedIn: how many people the page showed. Only those with an email are sent in `profiles`; this keeps the
    # page counted (and the run moving on) when nobody on it had one.
    scanned: int | None = Field(None, ge=0, le=1000)
    # LinkedIn: a one-line record of what was read on this page (cards, connection degrees, dialogs read, emails found),
    # kept on the run so an empty result can be explained afterwards. Never contains an email or a phone number.
    debug: str = Field("", max_length=1000)


class StartRunIn(BaseModel):
    source: Literal["naukri", "linkedin"] = "naukri"
    # False = read this source's site now, even if matches are waiting in the pool. Used when one click checks both sources:
    # the second source must actually be read, not answered from what the first one left in the pool.
    use_pool: bool = True


class RunFailIn(BaseModel):
    reason: Literal["not_logged_in", "captcha", "restricted", "cancelled", "error"]
    detail: str = ""
    debug: str = Field("", max_length=1000)


class StatusUpdateIn(BaseModel):
    status: Literal["selected", "rejected", "on_hold"]
    note: str = ""


class ContactIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
