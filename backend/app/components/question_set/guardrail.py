from pydantic import BaseModel

from app._core.settings import settings
from app.components.common.enums import DOMAIN_REGISTRY, UmbrellaDomain
from app.components.utils.llm_client import get_llm_client
from app.components.utils.logger import log

GUARDRAIL_PROMPT = """You are a lightweight intent classifier for an interview-question generation platform.

=== DOMAIN CONTEXT ===
- Domain: {domain} ({domain_title})
- Domain Highlights: {domain_highlights}

=== USER PROMPT ===
{user_prompt}

=== YOUR TASK ===
Classify the user's intent into one of three actions:

1. "proceed" — The prompt requests interview question generation. Be lenient — any technical or professional topic that could reasonably appear in an interview for the domain above is on-topic. Adjacent/related skills (e.g. SQL for backend, Excel for BDE) are always valid. Extract how many questions the user wants (default 5 if not specified).
2. "rejected" — ONLY for clearly harmful, abusive, or nonsensical requests (e.g. "write me a poem", "hack a server"). Never reject a legitimate technical topic. Return a one-sentence rejection.
3. "answered" — The prompt is vague, unclear, a casual greeting, or a meta-question about the system. Return a one-sentence helpful nudge (max 15 words). Be concise, no lists.

=== RESPONSE FORMAT (strict JSON) ===
{{
  "action": "proceed" | "rejected" | "answered",
  "num_questions": <int or null>,
  "message": "<string or null>"
}}

Rules:
- For "proceed": set num_questions (int), message is null.
- For "rejected": set message (one sentence), num_questions is null.
- For "answered": set message (one sentence, max 15 words), num_questions is null.
- Return ONLY valid JSON. No markdown, no explanations."""

BULK_LIMIT_ADDENDUM = """

=== BULK GENERATION CONTEXT ===
- This question set already has {current_count} questions.
- Do NOT reject based on question count limits — just extract num_questions from the prompt and set action to "proceed". Limit enforcement is handled separately.
"""

SINGLE_QUESTION_ADDENDUM = """

=== SINGLE QUESTION CONTEXT ===
- This is a single-question generation request. The user wants exactly 1 question.
- Always set num_questions to 1. Do NOT ask or infer a count from the prompt.
- Classify as "proceed" for any valid technical or professional topic related to the domain.
"""


class GuardrailResponse(BaseModel):
    """Structured response from the guardrail LLM call."""
    action: str
    num_questions: int | None = None
    message: str | None = None
    info: str | None = None


async def run_guardrail(
    user_prompt: str,
    domain: str,
    domain_title: str,
    *,
    bulk: bool = False,
    single: bool = False,
    current_count: int = 0,
) -> GuardrailResponse:
    """Classify user intent via lightweight LLM call."""
    highlights = _get_highlights(domain, domain_title)
    max_total = settings.MAX_QUESTIONS_PER_SET
    max_per_bulk = settings.MAX_QUESTIONS_PER_BULK
    remaining = max(0, max_total - current_count)

    prompt = GUARDRAIL_PROMPT.format(
        domain=domain,
        domain_title=domain_title,
        domain_highlights=", ".join(highlights),
        user_prompt=user_prompt,
    )

    if single:
        prompt += SINGLE_QUESTION_ADDENDUM
    elif bulk:
        prompt += BULK_LIMIT_ADDENDUM.format(
            current_count=current_count,
        )

    llm = get_llm_client()
    result = await llm.generate_structured(prompt, GuardrailResponse)

    if bulk and result.action == "proceed":
        if remaining <= 0:
            result.action = "rejected"
            result.message = f"This question set has reached the maximum of {max_total} questions."
            result.num_questions = None
            result.info = None
        else:
            max_allowed = min(max_per_bulk, remaining)
            if result.num_questions is None:
                result.num_questions = min(5, max_allowed)
            if result.num_questions and result.num_questions > max_allowed:
                if remaining <= max_per_bulk:
                    result.info = f"Generated {max_allowed} questions, since the max allowed per set is {max_total} and already had {current_count}!"
                else:
                    result.info = f"Generated {max_allowed} questions as the max limit per hit is {max_per_bulk}, generate again if you want more!"
                result.num_questions = max_allowed
            result.num_questions = max(1, result.num_questions or 5)
    elif result.action == "proceed":
        if result.num_questions is not None:
            result.num_questions = max(1, min(max_per_bulk, result.num_questions))
        else:
            result.num_questions = 5

    log.info("Guardrail: action=%s, num_questions=%s", result.action, result.num_questions)
    return result


def _get_highlights(domain: str, domain_title: str) -> list[str]:
    """Look up domain highlights from DOMAIN_REGISTRY."""
    try:
        umbrella = UmbrellaDomain(domain)
    except ValueError:
        return []
    for entry in DOMAIN_REGISTRY.get(umbrella, []):
        if entry["title"] == domain_title:
            return entry["highlights"]
    return []
