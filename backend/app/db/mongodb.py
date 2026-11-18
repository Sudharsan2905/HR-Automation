from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app._core.settings import settings

_client: AsyncIOMotorClient | None = None


async def init_db():
    """Initialize Motor client and Beanie ODM with all document models."""
    global _client

    from app.components.auth.blacklist import BlacklistedToken
    from app.components.auth.models import User
    from app.components.evaluation.models import EvaluationResult
    from app.components.hiring.models import HiringCandidate, HiringEvent, HiringFlow
    from app.components.interview.models import Interview
    from app.components.jd_interview.models import JdInterview, JdReport
    from app.components.question_set.models import Answer, QuestionSet
    from app.components.session.models import SessionLog
    from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun
    from app.components.session.transcript import Transcript

    _client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(
        database=_client[settings.MONGO_DB_NAME],
        document_models=[
            User,
            Interview,
            QuestionSet,
            Answer,
            SessionLog,
            Transcript,
            EvaluationResult,
            BlacklistedToken,
            JdInterview,
            JdReport,
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
