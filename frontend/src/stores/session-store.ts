import { create } from "zustand";
import type { SessionPhase } from "@/types/session";

interface SessionState {
  phase: SessionPhase;
  sessionId: string | null;
  interviewId: string | null;
  totalQuestions: number;
  currentIndex: number;
  warnings: number;
  // Camera
  cameraAvailable: boolean;
  // LiveKit
  roomName: string | null;
  token: string | null;
  livekitUrl: string | null;
  aiSpeaking: boolean;
  aiPaused: boolean;
  finished: boolean;
  botActive: boolean;
  // Metadata
  interviewTitle: string | null;
  interviewerName: string | null;
  candidateName: string | null;
  domain: string | null;
  domainTitle: string | null;
  lobbyJoke: { question: string; punchline: string } | null;
  // Pre-fetched audio check data (loaded in background on candidate login, cleared after use)
  preparedAudioCheck: { question: string; punchline: string; question_audio: string; response_audio: string } | null;
  setPhase: (phase: SessionPhase) => void;
  setSession: (
    sessionId: string,
    interviewId: string,
    total: number,
    index: number,
    meta: {
      cameraAvailable: boolean;
      roomName: string;
      token: string;
      livekitUrl: string;
      interviewTitle: string;
      interviewerName: string;
      candidateName: string;
      domain: string;
      domainTitle: string;
    },
  ) => void;
  setProgress: (index: number, aiSpeaking: boolean, aiPaused: boolean, finished: boolean, botActive: boolean) => void;
  setLobbyJoke: (joke: { question: string; punchline: string }) => void;
  setPreparedAudioCheck: (data: { question: string; punchline: string; question_audio: string; response_audio: string } | null) => void;
  addWarning: () => void;
  reset: () => void;
}

export const useSessionStore = create<SessionState>()((set) => ({
  phase: "idle",
  sessionId: null,
  interviewId: null,
  totalQuestions: 0,
  currentIndex: 0,
  warnings: 0,
  cameraAvailable: true,
  roomName: null,
  token: null,
  livekitUrl: null,
  aiSpeaking: false,
  aiPaused: false,
  finished: false,
  botActive: true,
  interviewTitle: null,
  interviewerName: null,
  candidateName: null,
  domain: null,
  domainTitle: null,
  lobbyJoke: null,
  preparedAudioCheck: null,
  setPhase: (phase) => set({ phase }),
  setSession: (sessionId, interviewId, totalQuestions, currentIndex, meta) =>
    set({
      sessionId,
      interviewId,
      totalQuestions,
      currentIndex,
      phase: "lobby",
      cameraAvailable: meta.cameraAvailable,
      roomName: meta.roomName,
      token: meta.token,
      livekitUrl: meta.livekitUrl,
      interviewTitle: meta.interviewTitle,
      interviewerName: meta.interviewerName,
      candidateName: meta.candidateName,
      domain: meta.domain,
      domainTitle: meta.domainTitle,
    }),
  setProgress: (currentIndex, aiSpeaking, aiPaused, finished, botActive) => set({ currentIndex, aiSpeaking, aiPaused, finished, botActive }),
  setLobbyJoke: (lobbyJoke) => set({ lobbyJoke }),
  setPreparedAudioCheck: (preparedAudioCheck) => set({ preparedAudioCheck }),
  addWarning: () => set((s) => ({ warnings: s.warnings + 1 })),
  reset: () =>
    set({
      phase: "idle",
      sessionId: null,
      interviewId: null,
      totalQuestions: 0,
      currentIndex: 0,
      warnings: 0,
      cameraAvailable: true,
      roomName: null,
      token: null,
      livekitUrl: null,
      aiSpeaking: false,
      aiPaused: false,
      finished: false,
      botActive: true,
      interviewTitle: null,
      interviewerName: null,
      candidateName: null,
      domain: null,
      domainTitle: null,
      lobbyJoke: null,
      preparedAudioCheck: null,
    }),
}));
