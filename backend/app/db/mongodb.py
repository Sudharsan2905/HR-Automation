from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app._core.settings import settings

_client: AsyncIOMotorClient | None = None


async def init_db():
    """Initialize Motor client and Beanie ODM with all document models."""
    global _client

    from app.components.auth.blacklist import BlacklistedToken
    from app.components.auth.models import User
    from app.components.hiring.models import HiringCandidate, HiringEvent, HiringFlow
    from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun

    _client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(
        database=_client[settings.MONGO_DB_NAME],
        document_models=[
            User,
            BlacklistedToken,
            SourcingJd,
            SourcingRun,
            SourcedProfile,
            HiringFlow,
            HiringCandidate,
            HiringEvent,
        ],
    )


async def close_db():
    """Close the Motor client connection."""
    global _client
    if _client:
        _client.close()
        _client = None
