from datetime import datetime, timezone

from beanie import Document
from pydantic import Field


class SessionLog(Document):
    """Tracks active interview sessions."""

    interview_id: str
    candidate_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    current_question_index: int = 0
    is_active: bool = True
    camera_available: bool = True
    jwt_jti: str

    # LiveKit fields
    livekit_room_name: str | None = None
    ai_paused: bool = False
    interviewer_joined: bool = False

    class Settings:
        name = "session_logs"
        indexes = ["candidate_id", "interview_id"]
