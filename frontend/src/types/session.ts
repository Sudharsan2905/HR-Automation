export interface SessionStart {
  session_id: string;
  interview_id: string;
  total_questions: number;
  current_question_index: number;
  resumed: boolean;
  camera_available: boolean;
  room_name: string;
  token: string;
  livekit_url: string;
  interview_title: string;
  interviewer_name: string;
  candidate_name: string;
  domain: string;
  domain_title: string;
}

export interface Progress {
  current_question_index: number;
  total_questions: number;
  ai_speaking: boolean;
  ai_paused: boolean;
  finished: boolean;
  bot_active: boolean;
}

export type SessionPhase =
  | "idle"
  | "lobby"
  | "connected"
  | "completed";
