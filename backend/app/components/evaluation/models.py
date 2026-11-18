from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field


class QuestionEvaluation(BaseModel):
    """LLM-generated evaluation of a single Q&A exchange."""
    question: str
    asked_by: str  # "ai" | "panel"
    answer: str    # brief LLM-written summary of what candidate said
    feedback: str
    score: int     # 0-10


class EvaluationResult(Document):
    """Full evaluation result for a completed interview."""
    interview_id: str
    candidate_mail: str
    interviewer_id: str
    candidate_name: str = "Candidate"
    total_score: float
    max_score: float
    percentage: float
    is_partial: bool = False
    evaluated_results: list[QuestionEvaluation] = Field(default_factory=list)
    overall_feedback: str = ""
    strengths: list[str] = Field(default_factory=list)
    areas_for_improvement: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pdf_report_path: str | None = None
    conversation_pdf_path: str | None = None

    class Settings:
        name = "evaluation_results"
        indexes = ["interview_id", "interviewer_id"]
