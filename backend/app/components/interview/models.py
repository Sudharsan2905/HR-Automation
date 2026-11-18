from datetime import datetime, timezone

from beanie import Document
from pydantic import Field

from app.components.common.schemas import InterviewStatus


class Interview(Document):
    """Links a QuestionSet to a candidate."""
    interviewer_id: str
    candidate_mail: str
    question_set_id: str
    status: InterviewStatus = InterviewStatus.FINALIZED
    is_live: bool = False
    due_date: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "interviews"
        indexes = ["interviewer_id", "candidate_mail", "question_set_id", "status"]
