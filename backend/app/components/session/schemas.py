from pydantic import BaseModel


class SessionStartRequest(BaseModel):
    """Optional body for POST /session/start."""
    camera_available: bool = True


class SessionStartResponse(BaseModel):
    """Returned when session starts or resumes."""
    session_id: str
    interview_id: str
    total_questions: int
    current_question_index: int
    resumed: bool = False
    camera_available: bool = True
    room_name: str
    token: str
    livekit_url: str


class ProgressResponse(BaseModel):
    """Current session progress."""
    current_question_index: int
    total_questions: int
    ai_speaking: bool = False
    ai_paused: bool = False
    finished: bool = False
    bot_active: bool = True


class WatchTokenResponse(BaseModel):
    """Observer token for interviewer."""
    room_name: str
    token: str
    livekit_url: str


# --- Audio check (lobby mic & speaker test) ---

class AudioCheckResponse(BaseModel):
    """Joke + pre-cached MP3 audio for speaker test and mic confirmation."""
    question: str
    punchline: str
    question_audio: str   # base64 mp3 — played for speaker test
    response_audio: str   # base64 mp3 — played after mic VAD confirms speech
