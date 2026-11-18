"""Level 1 enums and shared constants."""

from enum import Enum


class QuestionType(str, Enum):
    MCQ_SINGLE = "mcq_single"
    MCQ_MULTI = "mcq_multi"
    ESSAY = "essay"


class SubmissionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    TERMINATED = "terminated"
    MALPRACTICE = "malpractice"


TERMINAL_STATUSES = {SubmissionStatus.COMPLETED, SubmissionStatus.TERMINATED, SubmissionStatus.MALPRACTICE}


class MalpracticeType(str, Enum):
    TAB_SWITCH = "tab_switch"
    MULTIPLE_FACES = "multiple_faces"
    FACE_ABSENCE = "face_absence"
    BACKGROUND_NOISE = "background_noise"
    COPY_PASTE = "copy_paste"
    AUDIO_VIOLATION = "audio_violation"
    FULLSCREEN_EXIT = "fullscreen_exit"
    SCREEN_SHARE_STOP = "screen_share_stop"
    DEVTOOLS_OPEN = "devtools_open"
    KEYBOARD_SHORTCUT = "keyboard_shortcut"
    EYE_DIRECTION = "eye_direction"
    SPEAKING = "speaking"
    NOTIFICATION_RECEIVED = "notification_received"


class ReaccessReasonCategory(str, Enum):
    POOR_NETWORK = "poor_network"
    CANDIDATE_REQUEST = "candidate_request"
    TECHNICAL_ISSUE = "technical_issue"
    OTHER = "other"
