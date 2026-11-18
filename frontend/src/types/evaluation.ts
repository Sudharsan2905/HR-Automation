export interface QuestionEvaluation {
  question: string;
  asked_by: string;  // "ai" | "panel"
  answer: string;
  feedback: string;
  score: number;     // 0-10
}

export interface EvaluationResult {
  id: string;
  interview_id: string;
  candidate_id: string;
  interviewer_id: string;
  candidate_name: string;
  candidate_mail: string;
  total_score: number;
  max_score: number;
  percentage: number;
  is_partial: boolean;
  overall_feedback: string;
  strengths: string[];
  areas_for_improvement: string[];
  evaluated_at: string;
  pdf_report_path: string | null;
  conversation_pdf_path: string | null;
  evaluated_results: QuestionEvaluation[];
}

export interface EvaluationSummary {
  id: string;
  interview_id: string;
  candidate_name: string;
  candidate_mail: string;
  total_score: number;
  max_score: number;
  percentage: number;
  is_partial: boolean;
  evaluated_at: string;
  has_pdf: boolean;
  has_transcript_pdf: boolean;
}

export interface EvaluationListResponse {
  total: number;
  items: EvaluationSummary[];
}
