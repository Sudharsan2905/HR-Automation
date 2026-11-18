export type StageKey = "jd" | "sourcing" | "level1" | "level2" | "report";
export type StageStatus = "pending" | "running" | "done" | "failed" | "waiting";

export interface FlowStage {
  key: StageKey;
  label: string;
  status: StageStatus;
  detail: string | null;
  error: string | null;
}

export interface FlowStepError {
  message: string;
  detail?: string | null;
}

export interface FlowStep {
  key: string;
  agent: string;
  title: string;
  description: string;
  status: string;
  progress?: { done: number; total: number } | null;
  detail?: string | null;
  error?: FlowStepError | null;
}

export interface FlowRunEvent {
  ts: string;
  step: string;
  level: "info" | "warn" | "error" | string;
  message: string;
}

export interface Level1Run {
  pipeline_id: string | null;
  status: string | null;
  /** Needed by the admin review endpoint; the backend should include it here or on each candidate. */
  assessment_id?: string | null;
  steps: FlowStep[];
  events: FlowRunEvent[];
}

export type Level1Status =
  | "not_started" | "invited" | "in_progress" | "evaluating" | "passed" | "failed" | "terminated";

export type Level2Status = "not_started" | "scheduled" | "in_progress" | "completed" | "report_ready";

export interface FlowCandidate {
  id: string;
  profile_id: string;
  name: string;
  email: string | null;
  score: number | null;
  level1: {
    status: Level1Status;
    percentage: number | null;
    submission_id: string | null;
    key_expires_at: string | null;
    assessment_id?: string | null;
  };
  level2: {
    status: Level2Status;
    interview_id: string | null;
    jd_interview_id: string | null;
    due_date: string | null;
    recommendation: string | null;
  };
  final_report_sent: boolean;
}

export interface FlowEvent {
  ts: string;
  stage: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface HiringFlow {
  jd: { id: string; title: string; analysis_status: string };
  settings: { pass_percent: number };
  stages: FlowStage[];
  level1_run: Level1Run | null;
  candidates: FlowCandidate[];
  events: FlowEvent[];
}

export interface HiringFlowSummary {
  jd_id: string;
  title: string;
  created_at: string;
  candidate_count: number;
  stage_summary: { level1_done: number; level2_done: number };
  current_stage: string;
}

/** Admin review of one Level 1 submission (tolerant: field names may vary slightly). */
export interface Level1MalpracticeEvent {
  type?: string;
  event_type?: string;
  message?: string;
  detail?: string;
  at?: string;
  ts?: string;
  timestamp?: string;
}

export interface Level1QuestionReview {
  id?: string;
  question_text: string;
  question_type?: string;
  options?: string[] | { id?: string; text?: string; label?: string }[] | null;
  candidate_answer?: unknown;
  is_correct?: boolean | null;
  correct_answer?: unknown;
  feedback?: string | null;
  score?: number | null;
  max_score?: number | null;
  malpractice_events?: Level1MalpracticeEvent[];
}

export interface Level1SubmissionReview {
  candidate_name?: string | null;
  candidate_email?: string | null;
  status?: string | null;
  percentage?: number | null;
  score?: number | null;
  max_score?: number | null;
  summary?: string | null;
  questions?: Level1QuestionReview[];
  answers?: Level1QuestionReview[];
  malpractice_events?: Level1MalpracticeEvent[];
  events?: Level1MalpracticeEvent[];
}
