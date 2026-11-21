import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app._core.security import create_access_token
from app._core.settings import settings
from app.components.auth.models import User
from app.components.auth.schemas import (
    CandidateLoginRequest,
    CandidateLinkRequest,
    LoginRequest,
    TokenResponse,
)
from app.components.common.schemas import Role, UserStatus
from app.components.utils.logger import log


def _name_from_email(email: str) -> str:
    """Derive display name from email local part (e.g. 'john.doe@x.com' → 'John Doe')."""
    local = email.split("@")[0]
    return " ".join(w.capitalize() for w in local.replace(".", " ").replace("_", " ").replace("-", " ").split())


async def login(req: LoginRequest) -> dict:
    """Admin login: the single super admin is compared against the env credentials."""
    if req.email != settings.SUPER_ADMIN_EMAIL or req.password != settings.SUPER_ADMIN_PASSWORD:
        raise HTTPException(401, "Invalid credentials")
    user = await _upsert_user(req.email, Role.SUPER_ADMIN, "Super Admin")
    return TokenResponse(access_token=_issue_token(user), role=user.role.value).model_dump()


def _candidate_token(user: User, scope: str) -> dict:
    """Candidate JWT; ``scope`` ("l1") restricts it to the Level 1 exam endpoints."""
    token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role.value,
            "email": user.email,
            "full_name": user.full_name or "",
            "scope": scope,
        },
        expires_minutes=settings.JWT_CANDIDATE_TOKEN_EXPIRE_MINUTES,
    )
    return TokenResponse(access_token=token, role=user.role.value).model_dump()


def _is_expired(when: datetime | None) -> bool:
    if when is None:
        return False
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)) < datetime.now(timezone.utc)


async def login_candidate(req: CandidateLoginRequest) -> dict:
    """Candidate login: Level 1 keys are reusable until they expire (time limit or exam submission)."""
    user = await User.find_one(User.email == req.email, User.role == Role.CANDIDATE)
    if not user:
        raise HTTPException(401, "Invalid credentials")

    if user.level1_key and secrets.compare_digest(user.level1_key, req.access_key):
        if _is_expired(user.level1_key_expires_at):
            raise HTTPException(401, "Level 1 access key expired. Contact the admin for a new key.")
        return _candidate_token(user, "l1")

    raise HTTPException(401, "Invalid access key")


async def issue_level1_key(user: User, ttl_hours: int | None = None) -> str:
    """Create a fresh Level 1 key for ``user`` (replaces any earlier one)."""
    key = secrets.token_urlsafe(16)
    user.level1_key = key
    hours = ttl_hours if ttl_hours is not None else settings.LEVEL1_KEY_TTL_HOURS
    user.level1_key_expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    return key


async def expire_level1_key(user: User) -> None:
    """Invalidate the Level 1 key (called when the exam is submitted)."""
    user.level1_key_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    user.updated_at = datetime.now(timezone.utc)
    await user.save()


async def link_candidate(req: CandidateLinkRequest, interviewer_id: str) -> dict:
    """Add a candidate (e.g. from Naukri sourcing) to the list (upsert by email)."""
    existing = await User.find_one(User.email == req.email, User.role == Role.CANDIDATE)
    if existing:
        return {
            "message": "Candidate already in list",
            "candidate_id": str(existing.id),
            "email": existing.email,
            "full_name": existing.full_name,
        }

    user = User(
        email=req.email,
        role=Role.CANDIDATE,
        status=UserStatus.ACTIVE,
        full_name=req.full_name,
        created_by=interviewer_id,
    )
    await user.insert()
    log.info("Candidate linked: %s (by %s)", req.email, interviewer_id)
    return {
        "message": "Candidate added to your list",
        "candidate_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
    }


async def delete_candidate(candidate_id: str, interviewer_id: str) -> dict:
    """Delete a candidate."""
    user = await User.get(candidate_id)
    if not user or user.role != Role.CANDIDATE:
        raise HTTPException(404, "Candidate not found")

    await user.delete()
    return {"message": "Candidate deleted"}


# --- Helpers ---

async def _upsert_user(email: str, role: Role, default_name: str) -> User:
    """Find or create a user record. Forces status=ACTIVE on existing records."""
    user = await User.find_one(User.email == email)
    if not user:
        user = User(email=email, role=role, status=UserStatus.ACTIVE, full_name=default_name)
        await user.insert()
    elif user.status != UserStatus.ACTIVE:
        user.status = UserStatus.ACTIVE
        user.updated_at = datetime.now(timezone.utc)
        await user.save()
    return user


def _issue_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "role": user.role.value,
        "email": user.email,
        "full_name": user.full_name or "",
    })
