from openai import AsyncOpenAI

from app._core.settings import settings
from app.components.utils.logger import log


class STTClient:
    """OpenAI STT singleton for answer transcription."""

    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """Transcribe audio bytes to text."""
        transcript = await self.client.audio.transcriptions.create(
            model=self.model,
            file=(filename, audio_bytes),
        )
        log.info("STT transcribed: %d chars from %s", len(transcript.text), filename)
        return transcript.text

    async def close(self):
        """Close underlying HTTP client."""
        await self.client.close()


_instance: STTClient | None = None


def init_stt_client():
    """Initialize STT singleton at startup."""
    global _instance
    _instance = STTClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_STT_MODEL,
    )
    log.info("STT client initialized: model=%s", settings.OPENAI_STT_MODEL)


def get_stt_client() -> STTClient:
    """Get the STT singleton."""
    if _instance is None:
        raise RuntimeError("STTClient not initialized — call init_stt_client() first")
    return _instance
