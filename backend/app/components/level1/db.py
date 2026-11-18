"""Motor database access and index setup for the Level 1 collections."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.components.auth.models import User

PIPELINES = "l1_pipelines"
PIPELINE_CANDIDATES = "l1_pipeline_candidates"
QUESTIONS = "l1_questions"
CATEGORIES = "l1_categories"
ASSESSMENTS = "l1_assessments"
SHARES = "l1_shares"
SUBMISSIONS = "l1_submissions"
VERSION_HISTORY = "l1_version_history"


def get_db() -> AsyncIOMotorDatabase:
    """Return the Motor database behind Beanie."""
    return User.get_motor_collection().database


async def ensure_indexes() -> None:
    """Create the indexes the Level 1 collections rely on."""
    db = get_db()
    await db[SUBMISSIONS].create_index([("assessment_id", 1), ("candidate_id", 1)], unique=True)
    await db[SHARES].create_index("share_link", unique=True)
    await db[PIPELINES].create_index("hiring_jd_id")
    await db[PIPELINES].create_index("assessment_id")
    await db[PIPELINE_CANDIDATES].create_index("pipeline_id")
    await db[VERSION_HISTORY].create_index([("submission_id", 1), ("version", 1)])
