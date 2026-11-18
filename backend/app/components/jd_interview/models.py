from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field


class JdProfile(BaseModel):
    """Structured view of the JD, extracted once and reused by the report."""
    role_title: str = ""
    seniority: str = ""
    experience_level: str = ""   # junior | mid | senior (inferred)
    level_rationale: str = ""
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class JdInterview(Document):
    """Parent record for the JD-based interview flow."""
    created_by: str
    title: str
    jd_text: str
    resume_text: str | None = None
    resume_filename: str | None = None
    difficulty_level: str = "auto"  # auto | easy | medium | pro
    num_questions: int = 10
    jd_profile: JdProfile = Field(default_factory=JdProfile)
    question_set_id: str
    question_skill_map: dict[str, str] = Field(default_factory=dict)  # question_id -> JD skill
    question_type_map: dict[str, str] = Field(default_factory=dict)   # question_id -> concept | project | scenario
    interview_id: str | None = None
    candidate_mail: str | None = None
    generation_status: str = "generating"  # generating | done | failed
    generation_error: str | None = None
    report_status: str = "none"  # none | generating | done | failed
    report_error: str | None = None
    report_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "jd_interviews"
        indexes = ["created_by", "question_set_id", "interview_id"]


class PerQuestionResult(BaseModel):
    question_id: str
    question: str
    jd_skill: str = ""
    question_type: str = ""
    expected_points: list[str] = Field(default_factory=list)
    answer_summary: str = ""
    covered_points: list[str] = Field(default_factory=list)
    missed_points: list[str] = Field(default_factory=list)
    score: int = 0
    feedback: str = ""


class SkillAlignment(BaseModel):
    skill: str
    importance: str  # must_have | nice_to_have
    level: str  # strong | partial | weak | not_assessed
    evidence: str = ""


class AnswerQuality(BaseModel):
    structure: str = ""
    relevance: str = ""
    depth: str = ""
    jd_priority_order: str = ""


class JdReport(Document):
    """AI report comparing a candidate's interview answers to the JD."""
    jd_interview_id: str
    interview_id: str
    candidate_mail: str
    candidate_name: str = "Candidate"
    is_partial: bool = False
    per_question: list[PerQuestionResult] = Field(default_factory=list)
    skill_alignment: list[SkillAlignment] = Field(default_factory=list)
    answer_quality: AnswerQuality = Field(default_factory=AnswerQuality)
    total_score: float = 0
    max_score: float = 0
    score_percentage: float = 0
    jd_match_percentage: float = 0   # weighted by skill importance, over assessed skills
    coverage_percentage: float = 0   # share of JD skill weight actually assessed
    recommendation: str = "borderline"  # strong_hire | hire | borderline | no_hire
    overall_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    resume_consistency: str | None = None
    model: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "jd_reports"
        indexes = ["jd_interview_id", "interview_id"]
