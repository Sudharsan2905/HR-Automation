import axios from "axios";
import type { GlobalResponse } from "@/types/api";
import { useAuthStore } from "@/stores/auth-store";
import type {
  ExamAnswer,
  ExamAssessment,
  ExamRoundResponse,
  ExamSessionState,
  ExamSubmission,
  ExamSubmissionStatusResponse,
  FinishRoundResponse,
  MalpracticeRecordResponse,
} from "@/types/level1-exam";

const BASE = "/level1/exam";

export const EXAM_KEY_EXPIRED_MESSAGE = "Your Level 1 access key has expired. Contact the admin.";

/**
 * Dedicated client for the exam routes: same envelope unwrapping + Bearer token as the
 * shared apiClient, but a 401 clears auth and rejects with `unauthorized: true` instead of
 * redirecting to /login (the exam shows its own access-key state).
 */
const apiClient = axios.create({ baseURL: process.env.NEXT_PUBLIC_API_URL });

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    const body = response.data as GlobalResponse;
    if (body && typeof body === "object" && "success" in body) {
      return body.success ? body.data : Promise.reject(body);
    }
    return response.data;
  },
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout();
      return Promise.reject({
        success: false,
        unauthorized: true,
        message: EXAM_KEY_EXPIRED_MESSAGE,
        data: null,
      });
    }
    const body = error.response?.data;
    if (body && typeof body === "object" && "message" in body) return Promise.reject(body);
    return Promise.reject({ success: false, message: error.message || "Network error", data: null });
  }
);

export const isExamUnauthorized = (e: unknown) =>
  !!e && typeof e === "object" && (e as { unauthorized?: boolean }).unauthorized === true;

export const getExamAssessment = (shareLink: string) =>
  apiClient.get<unknown, ExamAssessment>(`${BASE}/assessment/${shareLink}`);

export const startExamAssessment = (shareLink: string) =>
  apiClient.post<unknown, ExamSubmission>(`${BASE}/assessment/${shareLink}/start`);

export const getExamSubmissionStatus = (shareLink: string) =>
  apiClient.get<unknown, ExamSubmissionStatusResponse | null>(`${BASE}/submission/status`, {
    params: { share_link: shareLink },
  });

export const getExamRound = (submissionId: string) =>
  apiClient.get<unknown, ExamRoundResponse>(`${BASE}/submission/${submissionId}/round`);

export const saveExamAnswer = (submissionId: string, questionId: string, answer: ExamAnswer) =>
  apiClient.post<unknown, { saved: boolean }>(`${BASE}/submission/${submissionId}/answer`, {
    question_id: questionId,
    answer,
  });

export const startExamInterview = (submissionId: string) =>
  apiClient.post<unknown, unknown>(`${BASE}/submission/${submissionId}/start-round`);

export const finishExamRound = (submissionId: string) =>
  apiClient.post<unknown, FinishRoundResponse>(`${BASE}/submission/${submissionId}/finish-round`);

export const uploadExamScreenshot = (submissionId: string, blob: Blob) => {
  const fd = new FormData();
  fd.append("file", blob, "screenshot.jpg");
  return apiClient.post<unknown, unknown>(`${BASE}/submission/${submissionId}/screenshot`, fd);
};

export const flagExamMalpractice = (submissionId: string, form: FormData) =>
  apiClient.post<unknown, MalpracticeRecordResponse>(
    `${BASE}/submission/${submissionId}/malpractice`,
    form
  );

export const uploadExamMalpracticeMedia = (
  submissionId: string,
  eventIndex: number,
  form: FormData
) =>
  apiClient.post<unknown, unknown>(
    `${BASE}/submission/${submissionId}/malpractice/${eventIndex}/media`,
    form
  );

export const getExamSessionState = (submissionId: string) =>
  apiClient.get<unknown, ExamSessionState>(`${BASE}/submission/${submissionId}/session-state`);

/** WebSocket URL for the live interview session (token sent as query param). */
export function examWebSocketUrl(submissionId: string, token: string): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  let base: string;
  if (env && /^https?:\/\//.test(env)) base = env.replace(/\/$/, "");
  else
    base = `${window.location.origin}${env && env.startsWith("/") ? env.replace(/\/$/, "") : "/api"}`;
  const wsBase = base.replace(/^http/, "ws");
  return `${wsBase}/ws/interview/${submissionId}?token=${encodeURIComponent(token)}`;
}

/** Extract a message from an apiClient rejection. */
export function examErrorMessage(e: unknown, fallback = ""): string {
  if (e && typeof e === "object" && "message" in e) {
    const m = (e as { message?: unknown }).message;
    if (typeof m === "string" && m) return m;
  }
  return fallback;
}
