from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app._core.security import decode_access_token
from app.components.auth.blacklist import is_token_blacklisted
from app.components.auth.models import User
from app.components.common.schemas import Role

_bearer = HTTPBearer()
_L1_PATHS = ("/api/level1/exam", "/api/ws/interview")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> User:
    """Decode JWT, check blacklist, return the authenticated user."""
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    if await is_token_blacklisted(payload.get("jti", "")):
        raise HTTPException(401, "Token has been revoked")

    user = await User.get(payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")

    # Level 1 candidate tokens only work on the Level 1 exam endpoints and its websocket
    path = request.url.path
    if payload.get("scope") == "l1" and not path.startswith(_L1_PATHS):
        raise HTTPException(403, "Level 1 access key cannot be used here")

    # Stash payload on request for session module to access jti
    request.state.jwt_payload = payload
    return user


async def get_effective_user(
    user: User = Depends(get_current_user),
    x_impersonate_user: str | None = Header(None),
) -> User:
    """Returns impersonated user if admin + header, else current user."""
    if not x_impersonate_user:
        return user
    if user.role != Role.SUPER_ADMIN:
        raise HTTPException(403, "Only admins can impersonate")
    target = await User.get(x_impersonate_user)
    if not target:
        raise HTTPException(404, "Impersonated user not found")
    return target


def _scope(request: Request) -> str:
    return (getattr(request.state, "jwt_payload", None) or {}).get("scope", "")


def require_role(*roles: Role):
    """Dependency factory — restrict endpoint to specific roles.

    The super admin may do everything an interviewer can. Level 1 candidate tokens
    (scope "l1") are rejected here: they only work on the Level 1 exam endpoints.
    """

    async def _check(request: Request, user: User = Depends(get_current_user)) -> User:
        allowed = set(roles) | ({Role.SUPER_ADMIN} if Role.INTERVIEWER in roles else set())
        if user.role not in allowed:
            raise HTTPException(403, "Insufficient permissions")
        if user.role == Role.CANDIDATE and _scope(request) == "l1":
            raise HTTPException(403, "Level 1 access key cannot be used here")
        return user

    return _check


async def require_level1_candidate(
    request: Request, user: User = Depends(get_current_user)
) -> User:
    """Candidate authenticated with a Level 1 key (reusable until it expires)."""
    from app.components.auth.service import _is_expired

    if user.role != Role.CANDIDATE or _scope(request) != "l1":
        raise HTTPException(403, "Level 1 candidates only")
    if _is_expired(user.level1_key_expires_at):
        raise HTTPException(401, "Level 1 access key expired")
    return user
