export type ExamSubmissionStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "malpractice"
  | "on_hold"
  | "terminated";

export type MalpracticeType =
  | "tab_switch"
  | "fullscreen_exit"
  | "screen_share_stop"
  | "devtools_open"
  | "copy_paste"
  | "keyboard_shortcut"
  | "multiple_faces"
  | "face_absence"
  | "eye_direction"
  | "background_noise"
  | "audio_violation"
  | "speaking"
  | "notification_received";

export interface ExamMonitoringConfig {
  tab_monitoring: boolean;
  audio_monitoring: boolean;
  video_monitoring: boolean;
  screenshot_enabled: boolean;
  screenshot_mode?: "time_interval" | "count";
  screenshot_interval_seconds?: number | null;
  screenshot_count?: number | null;
}

export interface ExamRoundConfig {
  round_number: number;
  question_count: number;
  max_duration_minutes: number;
}

export interface ExamAssessment {
  id: string;
  name: string;
  description?: string;
  accessibility?: "normal" | "monitoring";
  rounds: ExamRoundConfig[];
  monitoring_config?: Partial<ExamMonitoringConfig>;
}

export interface ExamQuestionOption {
  id: string;
  text: string;
  image_url?: string | null;
}

export interface ExamQuestion {
  id: string;
  text: string;
  type: "mcq_single" | "mcq_multiple" | "essay";
  image_url?: string | null;
  options?: ExamQuestionOption[];
}

export interface ExamRound {
  round_number: number;
  questions: ExamQuestion[];
  max_duration_minutes: number;
}

export interface ExamRoundResponse extends Partial<ExamMonitoringConfig> {
  round: ExamRound;
  remaining_seconds?: number | null;
  current_question_idx?: number;
  session_status?: ExamSubmissionStatus;
}

export interface ExamSubmission {
  id: string;
  status?: ExamSubmissionStatus;
  current_round?: number;
}

export interface ExamSubmissionStatusResponse {
  submission_id: string;
  status: ExamSubmissionStatus;
  assessment_id: string;
  candidate_id: string;
  current_round: number;
  completed_at?: string | null;
  paused_at?: string | null;
  malpractice_count: number;
}

export interface ExamSessionState {
  status: ExamSubmissionStatus;
  remaining_seconds: number | null;
  current_question_idx: number;
  current_round: number;
}

export interface FinishRoundResponse {
  completed: boolean;
  next_round?: number;
}

export interface MalpracticeRecordResponse {
  malpractice_count: number;
  is_terminal: boolean;
  event_index?: number | null;
  current_round: number;
}

export type ExamWsMessageType =
  | "connected"
  | "on_hold"
  | "resume_approved"
  | "terminated"
  | "pong"
  | "error"
  | "admin_warning";

export interface ExamWsMessage {
  type: ExamWsMessageType;
  status?: string;
  remaining_seconds?: number | null;
  current_question_idx?: number;
  message?: string;
}

export type ExamAnswer = string | string[];
export type ExamAnswerMap = Record<string, ExamAnswer>;

export type ExamNetworkStatus = "connected" | "reconnecting" | "offline" | "on_hold";
