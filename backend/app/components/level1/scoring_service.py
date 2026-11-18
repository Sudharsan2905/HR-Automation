"""MCQ scoring in Python and batched LLM essay scoring."""

import json
import re
from typing import Any, cast

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app._core.settings import settings
from app.components.level1 import db as l1db
from app.components.utils.logger import log

_MCQ_TYPES = ("mcq_single", "mcq_multiple", "mcq_multi")
_SCORING_ERROR = {"is_correct": None, "feedback": "Scoring error"}
Essay = tuple[str, str, str, str]


def _score_mcq(original: dict, given_answer: Any) -> tuple[int, bool]:
    """Return (score, is_correct) for an MCQ answer."""
    correct_options = [o for o in original.get("options", []) if o.get("is_correct")]
    correct_ids = {str(o["_id"]) if "_id" in o else o.get("id", "") for o in correct_options}
    correct_texts = {o.get("text", "").strip() for o in correct_options}
    given = [given_answer] if isinstance(given_answer, str) else (given_answer or [])
    given_set = {str(g).strip() for g in given}
    is_correct = bool(given) and (given_set == correct_ids or given_set == correct_texts)
    return (1 if is_correct else 0), is_correct


def _collect_round(rd: dict, originals: dict, essays: list[Essay]) -> tuple[int, int, dict[str, dict]]:
    """Score MCQs inline and append essays to ``essays``; returns (correct_mcq, total, mcq_results)."""
    answers = rd.get("answers", {})
    correct_mcq = 0
    total = 0
    mcq_results: dict[str, dict] = {}
    for q in rd.get("questions", []):
        qid = q.get("id", "")
        original = originals.get(qid, {})
        answer = answers.get(qid)
        total += 1
        if q.get("type", "essay") in _MCQ_TYPES:
            score, is_correct = _score_mcq(original, answer)
            correct_mcq += score
            mcq_results[qid] = {"is_correct": is_correct}
            continue
        q_text = q.get("text", "") or original.get("question_text", "")
        essays.append((qid, q_text, original.get("correct_answer", ""), answer if isinstance(answer, str) else ""))
    return correct_mcq, total, mcq_results


def _parse_essay_results(text: str) -> list[dict]:
    """Parse the model reply: tolerate ```json fences and a {"results": [...]} wrapper."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group())
    if isinstance(data, dict):
        data = data.get("results") or next((v for v in data.values() if isinstance(v, list)), [])
    return cast(list, data)


def _build_essay_prompt(essays: list[Essay]) -> str:
    numbered = "\n\n".join(
        f"[{i + 1}] Question ID: {qid}\nQuestion: {q_text}\nExpected Answer: {expected}\nCandidate Answer: {ans}"
        for i, (qid, q_text, expected, ans) in enumerate(essays)
    )
    return (
        f"Score the following {len(essays)} essay answer(s).\n"
        "For each, evaluate keyword and content similarity. Mark correct if similarity > 80%. "
        "Nonsensical or empty answers are incorrect. Return one result for EVERY question.\n\n"
        f"{numbered}\n\n"
        "Return ONLY a valid JSON array (one object per question):\n"
        '[{"question_id": "<id>", "is_correct": true/false, "feedback": "<string>"}, ...]'
    )


def _result(r: dict) -> dict:
    return {"is_correct": r.get("is_correct"), "feedback": r.get("feedback", "")}


def _match_results(results: list, expected_ids: list[str]) -> dict[str, dict]:
    """Match results by question id; fall back to position when the model altered the ids."""
    valid = [r for r in results if isinstance(r, dict) and r.get("is_correct") is not None]
    by_id = {str(r.get("question_id")): _result(r) for r in valid}
    if len(results) == len(expected_ids) and not set(by_id) >= set(expected_ids):
        by_id = {
            qid: _result(r)
            for qid, r in zip(expected_ids, results, strict=True)
            if isinstance(r, dict) and r.get("is_correct") is not None
        }
    return {qid: by_id[qid] for qid in expected_ids if qid in by_id}


async def _call_essay_llm(essays: list[Essay]) -> dict[str, dict]:
    """One LLM call for ``essays``; returns qid -> result for the essays it answered."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2)
    response = await client.chat.completions.create(
        model=settings.LEVEL1_ANALYSIS_MODEL,
        max_tokens=250 * len(essays) + 300,
        messages=[{"role": "user", "content": _build_essay_prompt(essays)}],
    )
    results = _parse_essay_results((response.choices[0].message.content or "").strip())
    return _match_results(results, [qid for qid, *_ in essays])


async def _score_essays_batch(essays: list[Essay]) -> dict[str, dict]:
    """Score all essays with one LLM call, re-asking once for any essay it skipped."""
    if not essays:
        return {}
    if not settings.OPENAI_API_KEY:
        return {qid: {"is_correct": None, "feedback": "Scoring unavailable"} for qid, *_ in essays}
    scored: dict[str, dict] = {}
    pending = list(essays)
    for attempt in (1, 2):
        try:
            scored.update(await _call_essay_llm(pending))
        except Exception as exc:
            log.warning(f"Essay scoring attempt {attempt} failed: {type(exc).__name__}: {exc}")
        pending = [e for e in essays if e[0] not in scored]
        if not pending:
            break
    if pending:
        log.warning(f"Essay scoring incomplete: {len(pending)} of {len(essays)} unevaluated")
    return {qid: scored.get(qid, dict(_SCORING_ERROR)) for qid, *_ in essays}


async def _load_originals(db: AsyncIOMotorDatabase, rounds: list[dict]) -> dict[str, dict]:
    qids = [ObjectId(q["id"]) for rd in rounds for q in rd.get("questions", []) if q.get("id")]
    if not qids:
        return {}
    docs = await db[l1db.QUESTIONS].find({"_id": {"$in": qids}}).to_list(len(qids))
    return {str(d["_id"]): d for d in docs}


async def score_round(db: AsyncIOMotorDatabase, rd: dict) -> dict:
    """Score one round: MCQs in code, all essays in one LLM call."""
    originals = await _load_originals(db, [rd])
    essays: list[Essay] = []
    correct_mcq, total_questions, question_results = _collect_round(rd, originals, essays)
    correct_essay = 0
    for qid, res in (await _score_essays_batch(essays)).items():
        question_results[qid] = res
        correct_essay += 1 if res.get("is_correct") else 0
    total_correct = correct_mcq + correct_essay
    pct = round((total_correct / total_questions * 100) if total_questions > 0 else 0.0, 1)
    return {
        "score": total_correct,
        "percentage": pct,
        "total_questions": total_questions,
        "correctly_answered": total_correct,
        "wrong_answer": total_questions - total_correct,
        "question_results": question_results,
    }
