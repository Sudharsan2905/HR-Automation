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


class GlobalResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool
    message: str
    data: Any = None
    error: Any = None
