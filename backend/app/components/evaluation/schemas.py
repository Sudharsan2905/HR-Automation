from pydantic import BaseModel


class LLMQuestionEvaluation(BaseModel):
    """Single Q&A evaluation from LLM."""
    question: str
    asked_by: str  # "ai" | "panel"
    answer: str
    feedback: str
    score: int


class LLMTranscriptEvaluation(BaseModel):
    """Full LLM evaluation output for a transcript-based interview."""
    evaluated_results: list[LLMQuestionEvaluation]
    overall_feedback: str
    strengths: list[str]
    areas_for_improvement: list[str]
