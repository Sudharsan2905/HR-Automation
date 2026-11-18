import apiClient from "@/lib/api-client";
import type { EvaluationResult, EvaluationListResponse } from "@/types/evaluation";

export interface EvaluationListParams {
  skip?: number;
  limit?: number;
  candidate_search?: string;
  max_percentage?: number;
}

export const getAllEvaluations = (params?: EvaluationListParams) =>
  apiClient.get<unknown, EvaluationListResponse>("/evaluations/interviewer/all", { params });

export const getEvaluation = (interviewId: string) =>
  apiClient.get<unknown, EvaluationResult>(`/evaluations/${interviewId}`);

export const downloadReport = (interviewId: string) =>
  apiClient.get(`/evaluations/${interviewId}/report`, { responseType: "blob" });

export const downloadTranscript = (interviewId: string) =>
  apiClient.get(`/evaluations/${interviewId}/transcript`, { responseType: "blob" });
