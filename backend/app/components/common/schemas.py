from enum import Enum
from typing import Any

from pydantic import BaseModel


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


class UserStatus(str, Enum):
    PENDING_OTP = "pending_otp"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    REJECTED = "rejected"


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    PRO = "pro"


class InterviewStatus(str, Enum):
    FINALIZED = "finalized"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"


class QuestionSetStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"


class ContributionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    USED = "used"
    REJECTED = "rejected"


class GlobalResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool
    message: str
    data: Any = None
    error: Any = None
