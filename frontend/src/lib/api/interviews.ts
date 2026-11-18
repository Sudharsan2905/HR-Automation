import apiClient from "@/lib/api-client";
import type { InterviewDetail } from "@/types/interview";

export const getInterview = (id: string) =>
  apiClient.get<unknown, InterviewDetail>(`/interviews/${id}`);

export const deleteInterview = (id: string) =>
  apiClient.delete<unknown, { message: string }>(`/interviews/${id}`);
