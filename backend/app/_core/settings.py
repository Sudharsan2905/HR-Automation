from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Single source for all environment variables."""

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "skill_mate"

    # JWT
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_CANDIDATE_TOKEN_EXPIRE_MINUTES: int = 90

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""  # sender address; falls back to SMTP_USER (needed for relays like Brevo)
    SMTP_FROM_NAME: str = "SkillMate"

    # LLM
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # OpenAI TTS
    OPENAI_TTS_MODEL: str = "tts-1"
    OPENAI_TTS_VOICE: str = "nova"

    # OpenAI STT
    OPENAI_STT_MODEL: str = "gpt-4o-mini-transcribe"

    # Reports
    REPORT_STORAGE_PATH: str = "./reports"

    # Audio cache (pre-generated TTS for static joke audio checks)
    AUDIO_CACHE_PATH: str = "./audio_cache"

    # Super Admin Seed
    SUPER_ADMIN_EMAIL: str
    SUPER_ADMIN_PASSWORD: str

    # LLM Token Limits
    LLM_MAX_TOKENS_SINGLE_QUESTION: int = 2048
    LLM_MAX_TOKENS_BULK_QUESTIONS: int = 16384
    LLM_MAX_TOKENS_EVALUATION: int = 8192
    LLM_MAX_TOKENS_JD_GENERATION: int = 8192
    LLM_MAX_TOKENS_JD_REPORT: int = 8192

    # JD Interview module
    JD_MAX_CHARS: int = 24000
    RESUME_MAX_CHARS: int = 16000
    JD_DEFAULT_QUESTIONS: int = 10

    # Naukri sourcing module
    SOURCING_BATCH_SIZE: int = 5
    SOURCING_MIN_SCORE: int = 60
    SOURCING_PAGES_PER_RUN: int = 5        # most ResDex pages one click reads while looking for 5
    SOURCING_PREFETCH_PAGES: int = 2       # pages read into the pool once 5 are shortlisted
    SOURCING_MAX_PAGE: int = 20
    SOURCING_SCREEN_CHUNK: int = 10        # profiles per screening call
    SOURCING_SCREEN_CONCURRENCY: int = 4   # screening calls in flight at once
    LLM_MAX_TOKENS_SOURCING: int = 32000   # reasoning models spend part of this on hidden reasoning
    SOURCING_RUN_TIMEOUT_MINUTES: int = 20

    # Level 1 (AI-generated proctored exam)
    LEVEL1_PASS_PERCENT: int = 75           # candidates must score ABOVE this to reach Level 2
    LEVEL1_QUESTION_MODEL: str = "gpt-4o"
    LEVEL1_ANALYSIS_MODEL: str = "gpt-4o-mini"
    LEVEL1_QUESTION_COUNTS: dict[str, int] = {"mcq_single": 10, "mcq_multi": 6, "essay": 4}
    LEVEL1_EXAM_MINUTES: int = 60
    LEVEL1_KEY_TTL_HOURS: int = 72          # Level 1 access key expires after this, or on submission
    LEVEL1_STORAGE_PATH: str = "./level1_files"  # resumes, photos, proctoring screenshots
    LEVEL1_MAX_FILE_MB: int = 10
    LEVEL1_CONCURRENCY: int = 5
    LEVEL1_MAX_MALPRACTICE: int = 3         # strikes before the exam is terminated
    LEVEL1_MAX_REACCESS: int = 3            # admin re-access grants per candidate
    LEVEL1_HOLD_DELAY_SECONDS: int = 60     # websocket silence before the session goes ON_HOLD
    LEVEL2_DUE_DAYS: int = 3                # Level 2 due date = promotion time + this many days
    HIRING_AUTO_SELECT: bool = True         # shortlisted profiles are selected automatically

    # LiveKit
    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_CLIENT_URL: str = ""  # URL sent to browser — defaults to LIVEKIT_URL if empty
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    ENABLE_RECORDING: bool = False
    RECORDING_STORAGE_PATH: str = "./recordings"

    # App
    APP_NAME: str = "SkillMate"
    APP_URL: str = "http://localhost:3000"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    MAX_QUESTIONS_PER_SET: int = 100
    MAX_QUESTIONS_PER_BULK: int = 25

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
