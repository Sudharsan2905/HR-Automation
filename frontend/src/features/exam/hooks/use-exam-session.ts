"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  examErrorMessage,
  finishExamRound,
  getExamAssessment,
  getExamRound,
  startExamInterview,
} from "@/lib/api/level1-exam";
import type {
  ExamAnswer,
  ExamAnswerMap,
  ExamMonitoringConfig,
  ExamRound,
  ExamRoundConfig,
} from "@/types/level1-exam";
import { examPaths } from "../lib/constants";
import { markAssessmentDone } from "../lib/session-storage";
import { useAnswerSync } from "./use-answer-sync";
import { useExamSocket } from "./use-exam-socket";
import { useRoundTimer } from "./use-round-timer";

/**
 * Core exam session: loads the current round, owns answers/navigation/timer, talks to the
 * session WebSocket and finishes rounds. Proctoring lives in separate hooks.
 */
export function useExamSession({
  shareLink,
  submissionId,
  token,
}: {
  shareLink: string;
  submissionId: string;
  token: string | null;
}) {
  const router = useRouter();

  const [roundData, setRoundData] = useState<ExamRound | null>(null);
  const [assessmentRounds, setAssessmentRounds] = useState<ExamRoundConfig[]>([]);
  const [monitoringConfig, setMonitoringConfig] = useState<Partial<ExamMonitoringConfig>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answers, setAnswers] = useState<ExamAnswerMap>({});
  const [visited, setVisited] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [interviewStarted, setInterviewStarted] = useState(false);
  const [showTimeExpired, setShowTimeExpired] = useState(false);
  const [adminWarning, setAdminWarning] = useState<string | null>(null);

  const currentIdxRef = useRef(0);
  const roundDataRef = useRef<ExamRound | null>(null);
  const submittingRef = useRef(false);
  const startedRef = useRef(false);
  const finishRef = useRef<() => Promise<void>>(async () => {});
  // Bridges the socket (declared first) to the timer (needs the socket's network status).
  const timerApi = useRef<{ set: (n: number) => void; get: () => number }>({
    set: () => {},
    get: () => 0,
  });

  useEffect(() => {
    roundDataRef.current = roundData;
  }, [roundData]);

  const setIdx = useCallback((idx: number) => {
    currentIdxRef.current = idx;
    setCurrentIdx(idx);
  }, []);

  // ── answers ──
  const { setAnswer: syncAnswer, flushPending } = useAnswerSync(submissionId);
  const setAnswer = useCallback(
    (questionId: string, answer: ExamAnswer) => {
      setAnswers((prev) => ({ ...prev, [questionId]: answer }));
      syncAnswer(questionId, answer);
    },
    [syncAnswer]
  );

  // ── websocket ──
  const { networkStatus } = useExamSocket({
    submissionId,
    token,
    callbacks: {
      onSessionState: (remaining, idx) => {
        if (remaining !== null) timerApi.current.set(remaining);
        if (idx !== undefined && idx > 0) setIdx(idx);
      },
      onResumeApproved: (remaining, idx) => {
        if (remaining !== null) timerApi.current.set(remaining);
        setIdx(idx ?? 0);
        toast.success("Your interview has been resumed by the administrator.");
      },
      onTerminated: () => {
        toast.error("Your session has been terminated by an administrator.");
        setTimeout(() => router.replace(examPaths.entry(shareLink)), 2000);
      },
      onAdminWarning: setAdminWarning,
      getRemainingSeconds: () => timerApi.current.get(),
      getCurrentQuestionIdx: () => currentIdxRef.current,
    },
  });

  // ── timer (ticks only while connected and the round has started) ──
  const timerActive = interviewStarted && networkStatus === "connected" && !showTimeExpired;
  const { setTimeLeft, timeLeftRef, isLowTime, formattedTime } = useRoundTimer({
    active: timerActive,
    onExpired: useCallback(() => {
      if (!submittingRef.current) void finishRef.current().then(() => setShowTimeExpired(true));
    }, []),
  });
  useEffect(() => {
    timerApi.current = { set: setTimeLeft, get: () => timeLeftRef.current };
  }, [setTimeLeft, timeLeftRef]);

  // ── data ──
  const handleLoadError = useCallback(
    (e: unknown) => {
      const msg = examErrorMessage(e).toLowerCase();
      if (msg.includes("completed")) {
        markAssessmentDone(shareLink);
        router.replace(examPaths.completed(shareLink));
      } else if (msg.includes("terminated") || msg.includes("revoked") || msg.includes("malpractice")) {
        router.replace(examPaths.entry(shareLink));
      } else if (!msg || msg.includes("network") || msg.includes("internal") || msg.includes("server")) {
        setLoadError(
          "Your interview could not be started due to an internal server issue. Please contact the administrator."
        );
      } else {
        toast.error("Failed to load questions");
      }
    },
    [router, shareLink]
  );

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [res, assessment] = await Promise.all([
        getExamRound(submissionId),
        getExamAssessment(shareLink).catch(() => null),
      ]);
      if (res?.round) {
        setRoundData(res.round);
        setTimeLeft(res.remaining_seconds ?? (res.round.max_duration_minutes || 30) * 60);
        setMonitoringConfig({
          tab_monitoring: res.tab_monitoring ?? false,
          video_monitoring: res.video_monitoring ?? false,
          audio_monitoring: res.audio_monitoring ?? false,
          screenshot_enabled: res.screenshot_enabled ?? false,
          screenshot_interval_seconds: res.screenshot_interval_seconds,
          screenshot_count: res.screenshot_count,
        });
        const qi = res.current_question_idx ?? 0;
        setIdx(qi > 0 && qi < res.round.questions.length ? qi : 0);
      }
      if (assessment?.rounds) setAssessmentRounds(assessment.rounds);
    } catch (e) {
      handleLoadError(e);
    } finally {
      setIsLoading(false);
    }
  }, [submissionId, shareLink, setTimeLeft, setIdx, handleLoadError]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // ── navigation ──
  const navigateTo = useCallback((idx: number) => {
    const leaving = roundDataRef.current?.questions[currentIdxRef.current];
    if (leaving)
      setVisited((prev) => (prev.has(leaving.id) ? prev : new Set(prev).add(leaving.id)));
    currentIdxRef.current = idx;
    setCurrentIdx(idx);
  }, []);

  // ── lifecycle ──
  /** Called once per round when the candidate accepts the intro modal. */
  const beginRound = useCallback(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    navigator.clipboard?.writeText("").catch(() => undefined);
    void startExamInterview(submissionId)
      .catch(() => undefined)
      .finally(() => setInterviewStarted(true));
  }, [submissionId]);

  const finishRound = useCallback(async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      await flushPending();
      const res = await finishExamRound(submissionId);
      if (res?.completed) {
        markAssessmentDone(shareLink);
        router.replace(examPaths.completed(shareLink));
        return;
      }
      setRoundData(null);
      setIdx(0);
      setAnswers({});
      setVisited(new Set());
      setInterviewStarted(false);
      startedRef.current = false;
      submittingRef.current = false;
      setSubmitting(false);
      await loadData();
    } catch {
      toast.error("Failed to submit round");
      submittingRef.current = false;
      setSubmitting(false);
    }
  }, [submissionId, shareLink, router, flushPending, loadData, setIdx]);

  useEffect(() => {
    finishRef.current = finishRound;
  }, [finishRound]);

  return {
    roundData,
    assessmentRounds,
    monitoringConfig,
    isLoading,
    loadError,
    currentIdx,
    answers,
    visited,
    submitting,
    interviewStarted,
    networkStatus,
    timer: { isLowTime, formattedTime },
    timerActive,
    showTimeExpired,
    setShowTimeExpired,
    adminWarning,
    setAdminWarning,
    setAnswer,
    navigateTo,
    beginRound,
    finishRound,
  };
}
