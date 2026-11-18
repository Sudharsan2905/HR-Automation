"""Thin async wrapper around the OpenAI chat API that returns parsed JSON."""

import json
import re
from typing import Any

from fastapi import HTTPException

from app._core.settings import settings


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group())


def _fatal(exc: Exception, model: str) -> HTTPException | None:
    import openai

    if isinstance(exc, openai.AuthenticationError):
        return HTTPException(502, "OpenAI rejected the API key (HTTP 401). Set a valid OPENAI_API_KEY and restart the backend.")
    if isinstance(exc, openai.NotFoundError):
        return HTTPException(502, f"OpenAI model '{model}' was not found or your key has no access to it. Change LEVEL1_QUESTION_MODEL / LEVEL1_ANALYSIS_MODEL.")
    if isinstance(exc, openai.RateLimitError) and "insufficient_quota" in str(exc):
        return HTTPException(502, "OpenAI quota exhausted (insufficient_quota). Add billing credit to the key.")
    return None


async def chat_json(model: str, system: str, user: str, max_tokens: int = 2000, retries: int = 1) -> Any:
    """Call the model in JSON mode and return the parsed object (HTTP 502 on failure)."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(502, "OPENAI_API_KEY is not configured")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            response = await client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return _parse_json(response.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - retried then re-raised below
            if fatal := _fatal(exc, model):
                raise fatal from exc
            last_exc = exc
    raise HTTPException(502, f"LLM call failed ({type(last_exc).__name__}): {last_exc}")
