"""Shared fixtures: a throwaway Mongo database per test and a scripted fake LLM."""

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app._core.settings import settings
from app.components.auth.models import User

TEST_DB = "skill_mate_test"


def _sourcing_models() -> list:
    try:
        from app.components.sourcing.models import SourcedProfile, SourcingJd, SourcingRun
    except ImportError:
        return []
    return [SourcingJd, SourcingRun, SourcedProfile]


def _hiring_models() -> list:
    from app.components.auth.blacklist import BlacklistedToken
    from app.components.evaluation.models import EvaluationResult
    from app.components.hiring.models import HiringCandidate, HiringEvent, HiringFlow
    from app.components.interview.models import Interview
    from app.components.jd_interview.models import JdInterview, JdReport
    from app.components.question_set.models import QuestionSet

    return [BlacklistedToken, HiringFlow, HiringCandidate, HiringEvent, Interview, QuestionSet, JdInterview, JdReport,
            EvaluationResult]


@pytest_asyncio.fixture(autouse=True)
async def db():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await client.drop_database(TEST_DB)
    await init_beanie(database=client[TEST_DB], document_models=[User, *_sourcing_models(), *_hiring_models()])
    yield client[TEST_DB]
    await client.drop_database(TEST_DB)
    client.close()


class FakeLLM:
    """Returns queued objects in order, matched by the requested response schema."""

    def __init__(self):
        self._queue: list = []
        self.calls: list[tuple[str, type]] = []

    def queue(self, obj) -> None:
        self._queue.append(obj)

    async def generate_structured(self, prompt, response_schema, **kwargs):
        self.calls.append((prompt, response_schema))
        for i, obj in enumerate(self._queue):
            if isinstance(obj, response_schema):
                return self._queue.pop(i)
        raise AssertionError(f"FakeLLM: nothing queued for {response_schema.__name__}")


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
