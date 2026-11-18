"""Question agent: ONE call per JD producing a shared question set for all candidates."""

import secrets
from collections import Counter
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from app._core.settings import settings
from app.components.level1.llm_client import chat_json
from app.components.level1.schemas import QuestionSpec
from app.components.utils.logger import log

MIN_ESSAY_ANSWER_CHARS = 40

SYSTEM = (
    "You are a senior technical interviewer. Create interview questions as JSON: "
    '{"questions": [...]}. Each question has: question_text (string; wrap code in fenced '
    "markdown blocks), question_type (mcq_single|mcq_multi|essay), complexity (low|medium|high), "
    "options (array of {text, is_correct}; exactly 4 options for MCQ; mcq_single has exactly one "
    "correct, mcq_multi has 2 or 3 correct; omit for essay), correct_answer (string). "
    "MANDATORY: every essay question MUST include a complete, specific model answer in "
    "correct_answer (at least 3 sentences covering the key points an evaluator must look for); "
    "an essay without it is rejected. Cover the JD's core skills and the candidates' common focus topics. "
    "Mix complexity levels. No duplicates."
)


def summarize_candidates(analyses: list[dict]) -> str:
    """Compact aggregate: ranked skills/topics plus a short per-candidate line."""
    topics: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    lines = []
    for a in analyses:
        topics.update(t.strip().lower() for t in a.get("focus_topics", []) if t.strip())
        gaps.update(t.strip().lower() for t in a.get("missing_skills", []) if t.strip())
        lines.append(f"- {a.get('name') or 'Candidate'}: {', '.join(a.get('matched_skills', [])[:8])}")
    return (
        f"Top focus topics: {', '.join(t for t, _ in topics.most_common(15))}\n"
        f"Common skill gaps: {', '.join(t for t, _ in gaps.most_common(8))}\n"
        f"Candidates ({len(analyses)}):\n" + "\n".join(lines[:60])
    )


def _normalize_essay(q: dict[str, Any]) -> dict[str, Any] | None:
    q.pop("options", None)
    answer = q.get("correct_answer")
    if not isinstance(answer, str) or len(answer.strip()) < MIN_ESSAY_ANSWER_CHARS:
        return None  # model answer is mandatory for essays
    q["correct_answer"] = answer.strip()
    return q


def _normalize_mcq(q: dict[str, Any]) -> dict[str, Any]:
    q["options"] = [
        {"id": chr(97 + i), "text": str(o.get("text", "")), "is_correct": bool(o.get("is_correct"))}
        for i, o in enumerate(q.get("options") or [])
        if isinstance(o, dict)
    ]
    return q


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate with the question schema; return a Mongo-ready dict or None."""
    q = dict(raw)
    if q.get("complexity") not in ("low", "medium", "high"):
        q["complexity"] = "medium"
    normalized = _normalize_essay(q) if q.get("question_type") == "essay" else _normalize_mcq(q)
    if normalized is None:
        return None
    try:
        QuestionSpec.model_validate(normalized)
    except (ValidationError, ValueError):
        return None
    return normalized


async def _request(jd: str, summary: str, counts: dict[str, int]) -> list[dict]:
    spec = ", ".join(f"{n} x {t}" for t, n in counts.items() if n > 0)
    user = f"JOB DESCRIPTION:\n{jd[:6000]}\n\nCANDIDATE POOL:\n{summary}\n\nCreate exactly: {spec}."
    data = await chat_json(settings.LEVEL1_QUESTION_MODEL, SYSTEM, user, max_tokens=8000, retries=1)
    items = data.get("questions") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def _accept(raws: list, result: dict[str, list[dict]], counts: dict[str, int]) -> None:
    for raw in raws:
        q = _normalize(raw) if isinstance(raw, dict) else None
        t = q.get("question_type") if q else None
        if q and t in result and len(result[t]) < counts[t]:
            result[t].append(q)


async def generate_questions(jd_text: str, analyses: list[dict], counts: dict[str, int] | None = None) -> list[dict]:
    """Return exactly sum(counts) validated questions, with one repair pass for shortfalls."""
    counts = counts or dict(settings.LEVEL1_QUESTION_COUNTS)
    summary = summarize_candidates(analyses)
    result: dict[str, list[dict]] = {t: [] for t in counts}
    need = dict(counts)
    for attempt in range(2):
        _accept(await _request(jd_text, summary, need), result, counts)
        need = {t: counts[t] - len(result[t]) for t in counts}
        if not any(need.values()):
            break
        log.warning("Question agent shortfall (attempt %d): %s", attempt + 1, need)
    if any(need.values()):
        raise HTTPException(502, f"Could not generate required questions, missing: {need}")
    questions = [q for t in counts for q in result[t]]
    if any(q["question_type"] == "essay" and not q.get("correct_answer") for q in questions):
        raise HTTPException(502, "Essay question generated without a model answer")
    secrets.SystemRandom().shuffle(questions)
    return questions
