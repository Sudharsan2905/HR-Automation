"""Pydantic schemas for the Level 1 exam, review and question validation."""

from pydantic import BaseModel, Field, model_validator

from app.components.level1.constants import MalpracticeType, QuestionType, ReaccessReasonCategory


class QuestionOption(BaseModel):
    id: str = Field(..., min_length=1)
    text: str = ""
    is_correct: bool = False

    @model_validator(mode="after")
    def validate_content(self) -> "QuestionOption":
        if not self.text.strip():
            raise ValueError("Each option must have text")
        return self


class QuestionSpec(BaseModel):
    """Validates one generated question."""

    question_text: str = ""
    question_type: QuestionType
    complexity: str
    options: list[QuestionOption] | None = None
    correct_answer: str | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "QuestionSpec":
        if len(self.question_text.strip()) < 5:
            raise ValueError("Question must have text (min 5 characters)")
        options = self.options or []
        if self.question_type == QuestionType.ESSAY:
            if options:
                raise ValueError("Essay questions must not have options")
            return self
        correct = [o for o in options if o.is_correct]
        if not correct:
            raise ValueError("MCQ questions must have at least one correct option marked")
        if self.question_type == QuestionType.MCQ_SINGLE and len(correct) > 1:
            raise ValueError("MCQ single-choice questions must have exactly one correct option")
        return self


class SubmitAnswerRequest(BaseModel):
    question_id: str = Field(..., min_length=1)
    answer: str | list[str]


class MalpracticeRequest(BaseModel):
    type: MalpracticeType
    description: str | None = None


class ReaccessRequest(BaseModel):
    reason: str = Field("", max_length=500)
    reason_category: ReaccessReasonCategory = ReaccessReasonCategory.OTHER


class TerminateRequest(BaseModel):
    reason: str = Field("Terminated by administrator", max_length=500)


class AnswerSavedResponse(BaseModel):
    saved: bool


class MalpracticeRecordResponse(BaseModel):
    malpractice_count: int
    is_terminal: bool
    event_index: int | None = None
    current_round: int


class SessionStateResponse(BaseModel):
    status: str
    remaining_seconds: int | None = None
    current_question_idx: int
    current_round: int


class SubmissionStatusResponse(BaseModel):
    submission_id: str
    status: str
    assessment_id: str
    candidate_id: str
    current_round: int
    completed_at: str | None = None
    paused_at: str | None = None
    malpractice_count: int
