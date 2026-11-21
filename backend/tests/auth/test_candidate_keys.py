"""Candidate login: Level 1 key reuse, expiry, scope gating."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app._core.security import decode_access_token
from app.components.auth import service
from app.components.auth.schemas import CandidateLoginRequest, LoginRequest
from app.components.common.schemas import Role
from tests.sourcing.helpers import make_user


async def _candidate(email="cand@x.com"):
    return await make_user(email, Role.CANDIDATE, "Cand")


def _scope(token_resp: dict) -> str:
    return decode_access_token(token_resp["access_token"])["scope"]


async def test_level1_key_is_reusable_and_scoped():
    user = await _candidate()
    key = await service.issue_level1_key(user)
    first = await service.login_candidate(CandidateLoginRequest(email=user.email, access_key=key))
    second = await service.login_candidate(CandidateLoginRequest(email=user.email, access_key=key))
    assert _scope(first) == _scope(second) == "l1"


async def test_level1_key_expires_by_time_and_by_submission():
    user = await _candidate()
    key = await service.issue_level1_key(user, ttl_hours=-1)
    with pytest.raises(HTTPException) as exc:
        await service.login_candidate(CandidateLoginRequest(email=user.email, access_key=key))
    assert exc.value.status_code == 401
    key = await service.issue_level1_key(user)
    await service.expire_level1_key(user)
    with pytest.raises(HTTPException):
        await service.login_candidate(CandidateLoginRequest(email=user.email, access_key=key))


async def test_wrong_key_rejected():
    user = await _candidate()
    await service.issue_level1_key(user)
    with pytest.raises(HTTPException):
        await service.login_candidate(CandidateLoginRequest(email=user.email, access_key="nope"))


async def test_admin_login_is_env_only(monkeypatch):
    monkeypatch.setattr(service.settings, "SUPER_ADMIN_EMAIL", "admin@x.com")
    monkeypatch.setattr(service.settings, "SUPER_ADMIN_PASSWORD", "pw")
    ok = await service.login(LoginRequest(email="admin@x.com", password="pw"))
    assert ok["role"] == "super_admin"
    for email, pw in [("admin@x.com", "bad"), ("other@x.com", "pw")]:
        with pytest.raises(HTTPException):
            await service.login(LoginRequest(email=email, password=pw))


async def test_level1_token_rejected_on_other_endpoints():
    from fastapi import Request

    from app.components.auth.dependencies import require_role

    user = await _candidate()
    check = require_role(Role.CANDIDATE)

    class _Req:
        class state:
            jwt_payload = {"scope": "l1"}

    with pytest.raises(HTTPException) as exc:
        await check(_Req, user)
    assert exc.value.status_code == 403


async def test_super_admin_passes_interviewer_check():
    from app.components.auth.dependencies import require_role

    admin = await make_user("a@x.com", Role.SUPER_ADMIN, "A")

    class _Req:
        class state:
            jwt_payload = {}

    assert await require_role(Role.INTERVIEWER)(_Req, admin) is admin


async def test_level1_token_blocked_outside_level1_paths():
    from fastapi import HTTPException

    from app._core.security import create_access_token
    from app.components.auth.dependencies import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    user = await _candidate()
    token = create_access_token({"sub": str(user.id), "role": "candidate", "scope": "l1"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def req(path):
        class R:
            class url:
                pass
            class state:
                pass
        R.url.path = path
        return R

    with pytest.raises(HTTPException) as exc:
        await get_current_user(req("/api/interviews/abc"), creds)
    assert exc.value.status_code == 403
    assert (await get_current_user(req("/api/level1/exam/assessment/x"), creds)).id == user.id
    assert (await get_current_user(req("/api/ws/interview/x"), creds)).id == user.id
