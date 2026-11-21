from datetime import datetime, timezone

from beanie import Document
from pydantic import EmailStr, Field

from app.components.common.schemas import Role, UserStatus


class User(Document):
    """User document — covers all 3 roles."""

    email: EmailStr
    role: Role
    status: UserStatus = UserStatus.ACTIVE
    full_name: str | None = None
    level1_key: str | None = None  # reusable until it expires or the exam is submitted
    level1_key_expires_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
        indexes = ["email"]
