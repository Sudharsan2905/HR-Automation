import asyncio
import json
from typing import TypeVar

from pydantic import BaseModel

from app._core.settings import settings
from app.components.utils.logger import log

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Provider-agnostic LLM client with structured JSON output."""

    def __init__(self, provider: str, api_key: str, model: str, fallback_provider: str | None = None, fallback_api_key: str | None = None, fallback_model: str | None = None):
        self.provider = provider
        self.model = model
        self.fallback_provider = fallback_provider
        self.fallback_model = fallback_model
        self._clients: list = []
        # Learned OpenAI model quirks: newer models need max_completion_tokens and reject custom temperature.
        self._oa_completion_tokens = False
        self._oa_no_temperature = False

        if provider == "openai":
            from openai import AsyncOpenAI
            self._openai = AsyncOpenAI(api_key=api_key)
            self._clients.append(self._openai)
        elif provider == "gemini":
            from google import genai
            self._gemini = genai.Client(api_key=api_key)

        self._fallback_openai = None
        self._fallback_gemini = None
        if fallback_provider == "openai" and fallback_api_key:
            from openai import AsyncOpenAI
            self._fallback_openai = AsyncOpenAI(api_key=fallback_api_key)
            self._clients.append(self._fallback_openai)
        elif fallback_provider == "gemini" and fallback_api_key:
            from google import genai
            self._fallback_gemini = genai.Client(api_key=fallback_api_key)

    async def generate_structured(self, prompt: str, response_schema: type[T], attachments: list[str] | None = None, max_tokens: int | None = None, temperature: float | None = None) -> T:
        """Generate structured output from LLM, with fallback on failure."""
        try:
            return await self._call(self.provider, self.model, prompt, response_schema, attachments, max_tokens, temperature)
        except Exception as e:
            log.warning("Primary LLM (%s) failed: %s. Trying fallback...", self.provider, e)
            if self.fallback_provider:
                try:
                    return await self._call(self.fallback_provider, self.fallback_model, prompt, response_schema, attachments, max_tokens, temperature)
                except Exception as fb_err:
                    log.warning("Fallback LLM (%s) also failed: %s", self.fallback_provider, fb_err)
                    raise e  # report the primary provider's error, which is the one to fix
            raise

    async def generate_text(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate plain text response."""
        try:
            return await self._call_text(self.provider, self.model, prompt, max_tokens)
        except Exception as e:
            log.warning("Primary LLM (%s) failed: %s. Trying fallback...", self.provider, e)
            if self.fallback_provider:
                return await self._call_text(self.fallback_provider, self.fallback_model, prompt, max_tokens)
            raise

    async def close(self):
        """Close underlying HTTP clients."""
        for client in self._clients:
            await client.close()

    async def _call(self, provider: str, model: str, prompt: str, response_schema: type[T], attachments: list[str] | None, max_tokens: int | None, temperature: float | None = None) -> T:
        if provider == "openai":
            return await self._openai_structured(model, prompt, response_schema, attachments, max_tokens, temperature)
        if provider == "gemini":
            return await self._gemini_structured(model, prompt, response_schema, attachments, max_tokens, temperature)
        raise ValueError(f"Unknown provider: {provider}")

    async def _call_text(self, provider: str, model: str, prompt: str, max_tokens: int | None) -> str:
        if provider == "openai":
            return await self._openai_text(model, prompt, max_tokens)
        if provider == "gemini":
            return await self._gemini_text(model, prompt, max_tokens)
        raise ValueError(f"Unknown provider: {provider}")

    async def _openai_create(self, client, kwargs: dict):
        """Call chat.completions.create, adapting once per quirk the model reports (and remembering it)."""
        for _ in range(3):
            if self._oa_completion_tokens and "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
            if self._oa_no_temperature:
                kwargs.pop("temperature", None)
            try:
                return await client.chat.completions.create(**kwargs)
            except Exception as e:
                msg = str(e)
                if "max_completion_tokens" in msg and "max_tokens" in kwargs:
                    self._oa_completion_tokens = True
                elif "temperature" in msg and "temperature" in kwargs:
                    self._oa_no_temperature = True
                else:
                    raise
        return await client.chat.completions.create(**kwargs)

    async def _openai_structured(self, model: str, prompt: str, response_schema: type[T], attachments: list[str] | None, max_tokens: int | None, temperature: float | None = None) -> T:
        client = self._openai if self.provider == "openai" else self._fallback_openai
        messages = []
        if attachments:
            messages.append({"role": "user", "content": "\n\n---\n\n".join(attachments)})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = dict(model=model, messages=messages, response_format={"type": "json_object"}, temperature=0.7 if temperature is None else temperature)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await self._openai_create(client, kwargs)
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        log.info("OpenAI response received, tokens: %s", response.usage.total_tokens if response.usage else "N/A")
        return response_schema.model_validate(parsed)

    async def _gemini_structured(self, model: str, prompt: str, response_schema: type[T], attachments: list[str] | None, max_tokens: int | None, temperature: float | None = None) -> T:
        from google.genai import types

        client = self._gemini if self.provider == "gemini" else self._fallback_gemini
        full_prompt = prompt
        if attachments:
            full_prompt = "\n\n---\n\n".join(attachments) + "\n\n---\n\n" + prompt

        config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7 if temperature is None else temperature)
        if max_tokens:
            config.max_output_tokens = max_tokens

        response = await asyncio.to_thread(client.models.generate_content, model=model, contents=full_prompt, config=config)
        parsed = json.loads(response.text)
        log.info("Gemini response received")
        return response_schema.model_validate(parsed)

    async def _openai_text(self, model: str, prompt: str, max_tokens: int | None) -> str:
        client = self._openai if self.provider == "openai" else self._fallback_openai
        kwargs: dict = dict(model=model, messages=[{"role": "user", "content": prompt}], temperature=0.7)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        response = await self._openai_create(client, kwargs)
        return response.choices[0].message.content

    async def _gemini_text(self, model: str, prompt: str, max_tokens: int | None) -> str:
        client = self._gemini if self.provider == "gemini" else self._fallback_gemini
        response = await asyncio.to_thread(client.models.generate_content, model=model, contents=prompt)
        return response.text


_instance: LLMClient | None = None


def init_llm_client():
    """Initialize the LLM singleton at startup."""
    global _instance

    provider = settings.LLM_PROVIDER
    if provider == "openai":
        api_key, model = settings.OPENAI_API_KEY, settings.OPENAI_MODEL
        fb_provider = "gemini" if settings.GEMINI_API_KEY else None
        fb_key, fb_model = settings.GEMINI_API_KEY, settings.GEMINI_MODEL
    else:
        api_key, model = settings.GEMINI_API_KEY, settings.GEMINI_MODEL
        fb_provider = "openai" if settings.OPENAI_API_KEY else None
        fb_key, fb_model = settings.OPENAI_API_KEY, settings.OPENAI_MODEL

    _instance = LLMClient(
        provider=provider,
        api_key=api_key,
        model=model,
        fallback_provider=fb_provider,
        fallback_api_key=fb_key,
        fallback_model=fb_model,
    )
    log.info("LLM client initialized: primary=%s, fallback=%s", provider, fb_provider)


def get_llm_client() -> LLMClient:
    """Get the initialized LLM singleton."""
    if _instance is None:
        raise RuntimeError("LLMClient not initialized — call init_llm_client() first")
    return _instance
