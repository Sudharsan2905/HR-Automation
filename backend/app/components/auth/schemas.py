from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Admin login (env-based super admin)."""
    email: EmailStr
    password: str


class CandidateLoginRequest(BaseModel):
    """Candidate login with the Level 1 access key."""
    email: EmailStr
    access_key: str


class CandidateLinkRequest(BaseModel):
    """Add a candidate (e.g. sourced from Naukri) to the candidate list."""
    email: EmailStr
    full_name: str


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    role: str
