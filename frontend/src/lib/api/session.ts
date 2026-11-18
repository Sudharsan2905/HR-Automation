import apiClient from "@/lib/api-client";
import type { SessionStart, Progress } from "@/types/session";

export const startSession = (cameraAvailable: boolean = true) =>
  apiClient.post<unknown, SessionStart>("/session/start", { camera_available: cameraAvailable });

export const completeSession = () =>
  apiClient.post<unknown, { message: string; interview_id: string }>("/session/complete");

export const getProgress = () =>
  apiClient.get<unknown, Progress>("/session/progress");

export const nextQuestion = () =>
  apiClient.post<unknown, { status: string; next_index?: number; message?: string }>("/session/next-question");

// Audio check
export interface AudioCheckData {
  question: string;
  punchline: string;
  question_audio: string;  // base64 mp3 — speaker test
  response_audio: string;  // base64 mp3 — played after browser VAD confirms speech
}

export const getAudioCheck = () =>
  apiClient.get<unknown, AudioCheckData>(`/session/audio-check?_t=${Date.now()}`);

// Interviewer endpoints
export const getWatchToken = (interviewId: string) =>
  apiClient.get<unknown, { room_name: string; token: string; livekit_url: string }>(
    `/session/${interviewId}/watch-token`
  );

export const joinAsInterviewer = (interviewId: string) =>
  apiClient.post<unknown, { room_name: string; token: string; livekit_url: string }>(
    `/session/${interviewId}/join`
  );

export const interviewerPauseAi = (interviewId: string) =>
  apiClient.post<unknown, { message: string }>(`/session/${interviewId}/pause-ai`);

export const interviewerResumeAi = (interviewId: string) =>
  apiClient.post<unknown, { message: string }>(`/session/${interviewId}/resume-ai`);
