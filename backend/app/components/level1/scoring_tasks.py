"""Background scoring: score a round, retry unevaluated essays, then fire the hiring hook."""

import asyncio

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.components.level1 import db as l1db
from app.components.level1.scoring_service import score_round
from app.components.level1.utils import utcnow
from app.components.utils.logger import log

_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 5


def _cumulative(sub: dict, round_number: int, result: dict) -> tuple[int, float]:
    total_rounds = len(sub.get("rounds_data", []))
    others = [rd for rd in sub.get("rounds_data", []) if rd.get("round_number") != round_number and rd.get("score") is not None]
    pct = round((sum(rd.get("percentage", 0.0) for rd in others) + result["percentage"]) / total_rounds, 1)
    return sum(rd.get("score", 0) for rd in others) + result["score"], pct


async def _store_round(db: AsyncIOMotorDatabase, sub: dict, round_number: int, result: dict) -> None:
    score, pct = _cumulative(sub, round_number, result)
    now = utcnow()
    await db[l1db.SUBMISSIONS].update_one(
        {"_id": sub["_id"]},
        {"$set": {
            "rounds_data.$[rd].score": result["score"],
            "rounds_data.$[rd].percentage": result["percentage"],
            "rounds_data.$[rd].question_results": result["question_results"],
            "score": score, "percentage": pct, "scoring_completed_at": now, "updated_at": now,
        }},
        array_filters=[{"rd.round_number": round_number}],
    )


async def notify_final(submission_id: str) -> None:
    """Call the hiring hook once a submission is fully scored (never raises)."""
    try:
        from app.components.hiring.service import on_level1_final

        await on_level1_final(submission_id)
    except Exception as exc:
        log.error("Level 1 final hook failed: submission_id=%s error=%s: %s", submission_id, type(exc).__name__, exc)


async def _retry(db: AsyncIOMotorDatabase, submission_id: str, round_number: int, attempt: int, unresolved: int) -> None:
    log.warning(f"Scoring: {unresolved} answer(s) unevaluated for {submission_id}; retry {attempt}/{_MAX_ATTEMPTS - 1}")
    await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
    await calculate_and_store_score(db, submission_id, round_number, attempt + 1)


async def calculate_and_store_score(db: AsyncIOMotorDatabase, submission_id: str, round_number: int, _attempt: int = 1) -> None:
    """Score one round, persist results, retry unevaluated answers, then call the hiring hook."""
    try:
        sub = await db[l1db.SUBMISSIONS].find_one({"_id": ObjectId(submission_id)})
        target = next((rd for rd in (sub or {}).get("rounds_data", []) if rd.get("round_number") == round_number), None)
        if not sub or not target:
            log.warning(f"Scoring: submission/round not found submission_id={submission_id} round={round_number}")
            return
        result = await score_round(db, target)
        await _store_round(db, sub, round_number, result)
        log.info(f"Round {round_number} scored: submission_id={submission_id} pct={result['percentage']:.1f}%")
        unresolved = sum(1 for r in result["question_results"].values() if r.get("is_correct") is None)
        if unresolved and _attempt < _MAX_ATTEMPTS:
            await _retry(db, submission_id, round_number, _attempt, unresolved)
            return
        if unresolved:
            log.warning(f"Scoring: {unresolved} answer(s) still unevaluated for {submission_id}; hook not called")
            return
        await notify_final(submission_id)
    except Exception as exc:
        log.error(f"Scoring failed: submission_id={submission_id} round={round_number} error={type(exc).__name__}: {exc}")
