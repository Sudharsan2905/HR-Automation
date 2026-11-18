import apiClient from "@/lib/api-client";
import type { HiringFlow, HiringFlowSummary, Level1SubmissionReview } from "@/types/hiring";

export const listHiringFlows = () =>
  apiClient.get<unknown, HiringFlowSummary[]>("/hiring/flows");

export const getHiringFlow = (jdId: string) =>
  apiClient.get<unknown, HiringFlow>(`/hiring/jds/${jdId}/flow`);

export const startLevel1 = (jdId: string) =>
  apiClient.post<unknown, { pipeline_id: string }>(`/hiring/jds/${jdId}/level1/start`, {});

export const resendLevel1 = (hcId: string) =>
  apiClient.post<unknown, { sent: boolean }>(`/hiring/candidates/${hcId}/level1/resend`, {});

export const promoteCandidate = (hcId: string) =>
  apiClient.post<unknown, { interview_id: string }>(`/hiring/candidates/${hcId}/promote`, {});

export const resendLevel2Key = (hcId: string) =>
  apiClient.post<unknown, { sent: boolean }>(`/hiring/candidates/${hcId}/level2/resend-key`, {});

export const getLevel1Submission = (assessmentId: string, submissionId: string) =>
  apiClient.get<unknown, Level1SubmissionReview>(
    `/level1/assessments/${assessmentId}/submissions/${submissionId}`,
  );
