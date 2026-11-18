from datetime import datetime, timezone

from beanie import Document
from pydantic import Field


class Transcript(Document):
    """Single utterance in an interview conversation."""

    interview_id: str
    role: str  # "ai" | "candidate" | "interviewer"
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "transcripts"
        indexes = ["interview_id"]
