export type InterviewStatus = "finalized" | "completed" | "partially_completed";

export interface InterviewSummary {
  id: string;
  candidate_mail: string;
  candidate_name: string;
  question_set_id: string;
  tags: string[];
  domain: string | null;
  domain_title: string | null;
  difficulty_level: string | null;
  num_questions: number;
  status: InterviewStatus;
  is_live: boolean;
  due_date: string | null;
  created_at: string;
}

export interface InterviewDetail extends InterviewSummary {
  interviewer_id: string;
  title?: string;
  access_key?: string;
  questions?: {
    id: string;
    question: string;
    topic: string;
    expected_points: string[];
    follow_ups: { id: string; question: string }[];
  }[];
}
