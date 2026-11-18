from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field, field_validator

from app.components.common.schemas import DifficultyLevel, QuestionSetStatus


class FollowUp(BaseModel):
    """Follow-up question embedded within a main question."""
    id: str = Field(default_factory=lambda: str(__import__("bson").ObjectId()))
    question: str


class Question(BaseModel):
    """Interview question — embedded in QuestionSet."""
    id: str = Field(default_factory=lambda: str(__import__("bson").ObjectId()))
    question: str
    topic: str
    expected_points: list[str]
    follow_ups: list[FollowUp] = []


class QuestionSet(Document):
    """Stores questions — vault or personal. Single collection."""
    title: str
    tags: list[str]
    created_by: str
    difficulty_level: DifficultyLevel
    domain: str
    domain_title: str
    questions: list[Question] = []
    status: QuestionSetStatus = QuestionSetStatus.DRAFT
    belongs_to_vault: bool = False
    forked_from: list[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("forked_from", mode="before")
    @classmethod
    def normalize_forked_from(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    class Settings:
        name = "question_sets"
        indexes = ["created_by", "belongs_to_vault", "domain", "status"]


class FollowUpAnswer(BaseModel):
    """Embedded follow-up answer."""
    follow_up_id: str
    question_text: str
    answer_text: str
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Answer(Document):
    """Candidate's answer to a single question — per interview."""
    interview_id: str
    question_id: str
    question_text: str
    answer_text: str
    follow_up_answers: list[FollowUpAnswer] = []
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "answers"
        indexes = ["interview_id", "question_id"]
