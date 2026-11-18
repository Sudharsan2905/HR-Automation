import pytest_asyncio
from beanie import init_beanie

from app.components.auth.models import User
from tests.conftest import _hiring_models, _sourcing_models


@pytest_asyncio.fixture(autouse=True)
async def _models(db):
    await init_beanie(database=db, document_models=[User, *_sourcing_models(), *_hiring_models()])
