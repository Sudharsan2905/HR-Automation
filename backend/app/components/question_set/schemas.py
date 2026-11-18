from pydantic import model_validator, BaseModel, field_validator

from app.components.common.schemas import DifficultyLevel


# --- Shared validation logic ---

def _check_topic_words(v):
    if v is not None and len(v.split()) > 4:
        raise ValueError("Topic must be 4 words or fewer")
    return v


def _check_max_points(v):
    if v is not None and len(v) > 4:
        raise ValueError("Expected points must have 4 items or fewer")
    return v


def _check_max_follow_ups(v):
    if v is not None and len(v) > 3:
        raise ValueError("Follow-ups must have 3 items or fewer")
    return v


# --- Schemas ---

class FollowUpInput(BaseModel):
    """Follow-up input for creating/editing questions."""
    question: str


class QuestionInput(BaseModel):
    """Question input with validation."""
    question: str
    topic: str
    expected_points: list[str]
    follow_ups: list[FollowUpInput] = []

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v): return _check_topic_words(v)

    @field_validator("expected_points")
    @classmethod
    def validate_points(cls, v): return _check_max_points(v)

    @field_validator("follow_ups")
    @classmethod
    def validate_follow_ups(cls, v): return _check_max_follow_ups(v)


class QuestionEditRequest(BaseModel):
    """Edit a single question — all fields optional."""
    question: str | None = None
    topic: str | None = None
    expected_points: list[str] | None = None
    follow_ups: list[FollowUpInput] | None = None

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v): return _check_topic_words(v)

    @field_validator("expected_points")
    @classmethod
    def validate_points(cls, v): return _check_max_points(v)

    @field_validator("follow_ups")
    @classmethod
    def validate_follow_ups(cls, v): return _check_max_follow_ups(v)


class CreateQuestionSetRequest(BaseModel):
    """Create an empty draft question set."""
    title: str
    difficulty_level: DifficultyLevel
    domain: str
    domain_title: str
    tags: list[str]

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if not v:
            raise ValueError("At least one tag is required")
        if len(v) > 5:
            raise ValueError("Maximum 5 tags allowed")
        return v


class LLMFollowUp(BaseModel):
    """Follow-up from LLM output."""
    question: str

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, v):
        """Models sometimes return follow-ups as bare strings instead of {"question": ...}."""
        return {"question": v} if isinstance(v, str) else v


class LLMQuestion(BaseModel):
    """Single question from LLM structured output."""
    question: str
    topic: str
    expected_points: list[str]
    follow_ups: list[LLMFollowUp] = []

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v): return _check_topic_words(v)

    @field_validator("expected_points")
    @classmethod
    def validate_points(cls, v): return _check_max_points(v)

    @field_validator("follow_ups")
    @classmethod
    def validate_follow_ups(cls, v): return _check_max_follow_ups(v)


class LLMQuestionResponse(BaseModel):
    """Full structured response from LLM."""
    tags: list[str] = []
    questions: list[LLMQuestion]


class SingleQuestionGenerateRequest(BaseModel):
    """Inline AI generation — single question from user prompt."""
    prompt: str


class BulkGenerateRequest(BaseModel):
    """Bulk AI generation — prompt only, num_questions from guardrail."""
    prompt_text: str
