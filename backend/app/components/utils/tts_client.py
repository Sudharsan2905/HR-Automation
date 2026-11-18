from openai import AsyncOpenAI

from app._core.settings import settings
from app.components.utils.logger import log


class TTSClient:
    """OpenAI TTS singleton for question audio generation."""

    def __init__(self, api_key: str, model: str, voice: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

    async def synthesize(self, text: str, response_format: str = "opus") -> bytes:
        """Convert text to speech. Default format is opus (for LiveKit); use 'mp3' for browser <audio> playback."""
        response = await self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format=response_format,
        )
        audio_bytes = response.content
        log.info("TTS generated: %d bytes for %d chars (format=%s)", len(audio_bytes), len(text), response_format)
        return audio_bytes

    async def close(self):
        """Close underlying HTTP client."""
        await self.client.close()


_instance: TTSClient | None = None


def init_tts_client():
    """Initialize TTS singleton at startup."""
    global _instance
    _instance = TTSClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_TTS_MODEL,
        voice=settings.OPENAI_TTS_VOICE,
    )
    log.info("TTS client initialized: model=%s, voice=%s", settings.OPENAI_TTS_MODEL, settings.OPENAI_TTS_VOICE)


def get_tts_client() -> TTSClient:
    """Get the TTS singleton."""
    if _instance is None:
        raise RuntimeError("TTSClient not initialized — call init_tts_client() first")
    return _instance
