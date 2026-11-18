from datetime import datetime

from pydantic import BaseModel, field_validator


class InterviewCreateRequest(BaseModel):
    """Create interview — pick existing candidate or provide email to get-or-create."""
    question_set_id: str
    candidate_id: str | None = None
    candidate_email: str | None = None
    candidate_name: str | None = None
    due_date: datetime

    @field_validator("due_date")
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
        if v.replace(tzinfo=None) < datetime.utcnow():
            raise ValueError("Due date must be in the future")
        return v
