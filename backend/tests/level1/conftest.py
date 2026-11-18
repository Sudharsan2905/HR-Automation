"""Level 1 fixtures: blacklist model for JWT auth, temp file storage, user + exam builders."""

import pytest
import pytest_asyncio
from beanie import init_beanie

from app._core.settings import settings
from app.components.auth.blacklist import BlacklistedToken
from app.components.auth.models import User
from app.components.common.schemas import Role
from app.components.level1 import db as l1db


@pytest_asyncio.fixture(autouse=True)
async def l1_setup(db, tmp_path, monkeypatch):
    await init_beanie(database=db, document_models=[User, BlacklistedToken])
    monkeypatch.setattr(settings, "LEVEL1_STORAGE_PATH", str(tmp_path / "files"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")


async def make_candidate(email: str = "asha@example.com", name: str = "Asha Rao") -> User:
    user = User(email=email, role=Role.CANDIDATE, full_name=name)
    await user.insert()
    return user


async def make_admin(email: str = "admin@example.com") -> User:
    user = User(email=email, role=Role.SUPER_ADMIN, full_name="Admin")
    await user.insert()
    return user


def make_questions() -> list[dict]:
    qs = []
    for t, n, correct in (("mcq_single", 10, 1), ("mcq_multi", 6, 2), ("essay", 4, 0)):
        for i in range(n):
            q = {"question_text": f"{t} question number {i}", "question_type": t, "complexity": "low"}
            if t == "essay":
                q["correct_answer"] = "A complete model answer covering the key points an evaluator needs."
            else:
                q["options"] = [{"text": f"o{k}", "is_correct": k < correct} for k in range(4)]
            qs.append(q)
    return qs


async def build_exam(emails: list[str], questions: int | None = None) -> dict:
    """Create an assessment + restricted share directly (no LLM) and return ids."""
    from app.components.level1.agents import assessment_agent

    qs = make_questions()
    qs = [{**q, "options": [{"id": chr(97 + i), **o} for i, o in enumerate(q.get("options", []))]} for q in qs]
    if questions:
        qs = qs[:questions]
    return await assessment_agent.build_assessment(
        l1db.get_db(), hiring_jd_id="jd1", user_id="u1", jd_title="Backend Dev",
        questions=qs, candidate_emails=emails, duration_minutes=30,
    )
