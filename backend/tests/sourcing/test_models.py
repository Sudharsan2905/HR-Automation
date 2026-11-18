import pytest
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.components.sourcing.models import SourcedProfile
from app.components.sourcing.schemas import LLMSkillFinding


async def test_source_link_unique_per_jd():
    await SourcedProfile(sourcing_jd_id="jd1", run_id="r1", source_link="https://x/1", name="A").insert()
    with pytest.raises(DuplicateKeyError):
        await SourcedProfile(sourcing_jd_id="jd1", run_id="r2", source_link="https://x/1", name="A").insert()


async def test_same_link_allowed_for_other_jd():
    await SourcedProfile(sourcing_jd_id="jd1", run_id="r1", source_link="https://x/1", name="A").insert()
    await SourcedProfile(sourcing_jd_id="jd2", run_id="r1", source_link="https://x/1", name="A").insert()
    assert await SourcedProfile.find_all().count() == 2


def test_screen_finding_rejects_unknown_match():
    with pytest.raises(ValidationError):
        LLMSkillFinding(skill="Django", match="maybe")
