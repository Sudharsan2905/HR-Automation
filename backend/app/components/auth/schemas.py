from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Admin login (env-based super admin)."""
    email: EmailStr
    password: str


class CandidateLoginRequest(BaseModel):
    """Candidate login with the access key for Level 1 or Level 2."""
    email: EmailStr
    access_key: str


class CandidateLinkRequest(BaseModel):
    """Add a candidate (e.g. sourced from Naukri) to the candidate list."""
    email: EmailStr
    full_name: str


class RegenerateKeyByEmailRequest(BaseModel):
    """Regenerate candidate access key by email."""
    email: EmailStr


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    role: str
