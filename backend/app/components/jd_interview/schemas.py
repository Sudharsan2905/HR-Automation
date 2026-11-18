from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# --- LLM output: JD analysis + question generation ---

class LLMJdProfile(BaseModel):
    role_title: str = ""
    seniority: str = ""
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class LLMFollowUp(BaseModel):
    question: str

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, v):
        """Models sometimes return follow-ups as bare strings instead of {"question": ...}."""
        return {"question": v} if isinstance(v, str) else v


class LLMJdQuestion(BaseModel):
    question: str
    type: str = "concept"  # concept | project | scenario
    topic: str
    jd_skill: str = ""
    expected_points: list[str] = Field(default_factory=list)
    follow_ups: list[LLMFollowUp] = Field(default_factory=list)


class LLMJdGeneration(BaseModel):
    is_valid_jd: bool = True
    invalid_reason: str = ""
    experience_level: str = ""  # junior | mid | senior
    level_rationale: str = ""
    jd_profile: LLMJdProfile = Field(default_factory=LLMJdProfile)
    tags: list[str] = Field(default_factory=list)
    questions: list[LLMJdQuestion] = Field(default_factory=list)


# --- LLM output: report ---

class LLMPerQuestion(BaseModel):
    question_index: int
    answer_summary: str = ""
    covered_points: list[str] = Field(default_factory=list)
    missed_points: list[str] = Field(default_factory=list)
    score: int = 0
    feedback: str = ""


class LLMSkillAlignment(BaseModel):
    skill: str
    level: str = "not_assessed"  # strong | partial | weak | not_assessed
    evidence: str = ""


class LLMAnswerQuality(BaseModel):
    structure: str = ""
    relevance: str = ""
    depth: str = ""
    jd_priority_order: str = ""


class LLMJdReport(BaseModel):
    per_question: list[LLMPerQuestion] = Field(default_factory=list)
    skill_alignment: list[LLMSkillAlignment] = Field(default_factory=list)
    answer_quality: LLMAnswerQuality = Field(default_factory=LLMAnswerQuality)
    recommendation: str = "borderline"
    overall_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    resume_consistency: str | None = None


# --- API requests ---

class AssignRequest(BaseModel):
    """Candidates can be from anywhere, so name and email are entered by the panel member."""
    candidate_name: str
    candidate_email: EmailStr
    due_date: str  # ISO datetime

    @field_validator("candidate_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2 or len(v) > 80:
            raise ValueError("Candidate name must be 2-80 characters")
        return v


class RegenerateRequest(BaseModel):
    question_id: str | None = None  # omit to regenerate the whole set (draft only)
