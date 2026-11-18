from datetime import datetime, timezone

from beanie import Document


class BlacklistedToken(Document):
    """Blacklisted JWT tokens — TTL index auto-purges expired entries."""

    jti: str
    expires_at: datetime

    class Settings:
        name = "blacklisted_tokens"
        indexes = ["jti"]


async def blacklist_token(jti: str, expires_at: datetime):
    """Add a JWT to the blacklist."""
    await BlacklistedToken(jti=jti, expires_at=expires_at).insert()


async def is_token_blacklisted(jti: str) -> bool:
    """Check if a JWT is blacklisted."""
    return await BlacklistedToken.find_one(BlacklistedToken.jti == jti) is not None


async def ensure_ttl_index():
    """Create TTL index on expires_at for automatic cleanup."""
    collection = BlacklistedToken.get_motor_collection()
    await collection.create_index("expires_at", expireAfterSeconds=0)
