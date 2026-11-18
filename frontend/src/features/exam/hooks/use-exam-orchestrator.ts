"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isDevToolsOpen } from "../lib/constants";
import type { ExamMonitoringConfig, ExamNetworkStatus } from "@/types/level1-exam";

export const ExamPhase = {
  IDLE: 0,
  VALIDATING_NETWORK: 1,
  VALIDATING_DEVTOOLS: 2,
  VALIDATING_VIDEO: 3,
  VALIDATING_AUDIO: 4,
  VALIDATING_SCREEN_SHARE: 5,
  VALIDATING_FULLSCREEN: 6,
  ACTIVE: 7,
} as const;
export type ExamPhase = (typeof ExamPhase)[keyof typeof ExamPhase];

export const EXAM_PHASE_LABELS: Record<ExamPhase, string> = {
  [ExamPhase.IDLE]: "Initializing exam environment…",
  [ExamPhase.VALIDATING_NETWORK]: "Checking network connectivity…",
  [ExamPhase.VALIDATING_DEVTOOLS]: "Checking developer tools…",
  [ExamPhase.VALIDATING_VIDEO]: "Requesting camera access…",
  [ExamPhase.VALIDATING_AUDIO]: "Requesting microphone access…",
  [ExamPhase.VALIDATING_SCREEN_SHARE]: "Requesting screen share…",
  [ExamPhase.VALIDATING_FULLSCREEN]: "Entering fullscreen mode…",
  [ExamPhase.ACTIVE]: "Exam Active",
};

interface Signals {
  networkStatus: ExamNetworkStatus;
  isDevtoolsOpen: boolean;
  isCameraReady: boolean;
  isAudioReady: boolean;
  isScreenShareReady: boolean;
  isFullscreen: boolean;
}

/**
 * Sequential validation state machine: network, devtools, camera, mic, screen
 * share, fullscreen, then ACTIVE. Steps disabled by the monitoring config are skipped.
 * Resource gates (shouldAcquire*) open one at a time so only one prompt shows.
 */
export function useExamOrchestrator({
  enabled,
  config,
  networkStatus,
  isCameraReady,
  isAudioReady,
  isScreenShareReady,
  isFullscreen,
}: {
  enabled: boolean;
  config: Partial<ExamMonitoringConfig>;
  networkStatus: ExamNetworkStatus;
  isCameraReady: boolean;
  isAudioReady: boolean;
  isScreenShareReady: boolean;
  isFullscreen: boolean;
}) {
  const [phase, setPhase] = useState<ExamPhase>(ExamPhase.IDLE);
  const [phaseError, setPhaseError] = useState<string | null>(null);
  const examActiveRef = useRef(false);
  const isPermissionFlowActiveRef = useRef(false);
  const [isDevtoolsOpen, setIsDevtoolsOpen] = useState(false);

  useEffect(() => {
    examActiveRef.current = phase === ExamPhase.ACTIVE && networkStatus === "connected";
  }, [phase, networkStatus]);

  useEffect(() => {
    const check = () => setIsDevtoolsOpen(isDevToolsOpen());
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const nextPhaseAfter = useCallback(
    (current: ExamPhase): ExamPhase => {
      const steps: Array<[ExamPhase, boolean]> = [
        [ExamPhase.VALIDATING_NETWORK, true],
        [ExamPhase.VALIDATING_DEVTOOLS, !!config.tab_monitoring],
        [ExamPhase.VALIDATING_VIDEO, !!config.video_monitoring],
        [ExamPhase.VALIDATING_AUDIO, !!config.audio_monitoring],
        [ExamPhase.VALIDATING_SCREEN_SHARE, !!(config.tab_monitoring || config.screenshot_enabled)],
        [ExamPhase.VALIDATING_FULLSCREEN, !!config.tab_monitoring],
        [ExamPhase.ACTIVE, true],
      ];
      const idx = steps.findIndex(([p]) => p === current);
      for (let i = idx + 1; i < steps.length; i++) if (steps[i][1]) return steps[i][0];
      return ExamPhase.ACTIVE;
    },
    [config]
  );

  useEffect(() => {
    if (!enabled || phase === ExamPhase.ACTIVE) return;
    const s: Signals = {
      networkStatus,
      isDevtoolsOpen,
      isCameraReady,
      isAudioReady,
      isScreenShareReady,
      isFullscreen,
    };
    let next: ExamPhase | undefined;
    switch (phase) {
      case ExamPhase.IDLE:
        next = ExamPhase.VALIDATING_NETWORK;
        break;
      case ExamPhase.VALIDATING_NETWORK:
        if (s.networkStatus === "connected") next = nextPhaseAfter(phase);
        break;
      case ExamPhase.VALIDATING_DEVTOOLS:
        if (!s.isDevtoolsOpen) next = nextPhaseAfter(phase);
        break;
      case ExamPhase.VALIDATING_VIDEO:
        if (s.isCameraReady) next = nextPhaseAfter(phase);
        break;
      case ExamPhase.VALIDATING_AUDIO:
        if (s.isAudioReady) next = nextPhaseAfter(phase);
        break;
      case ExamPhase.VALIDATING_SCREEN_SHARE:
        if (s.isScreenShareReady) next = nextPhaseAfter(phase);
        break;
      case ExamPhase.VALIDATING_FULLSCREEN:
        if (s.isFullscreen) next = ExamPhase.ACTIVE;
        break;
    }
    // State machine driven by external readiness signals.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (next !== undefined) setPhase(next);
  }, [
    enabled,
    phase,
    networkStatus,
    isDevtoolsOpen,
    isCameraReady,
    isAudioReady,
    isScreenShareReady,
    isFullscreen,
    nextPhaseAfter,
  ]);

  const markPermissionFlowStart = useCallback(() => {
    isPermissionFlowActiveRef.current = true;
  }, []);
  // Trailing window absorbs blur/focus events fired by the OS dialog.
  const markPermissionFlowEnd = useCallback(() => {
    setTimeout(() => {
      isPermissionFlowActiveRef.current = false;
    }, 3_000);
  }, []);

  /** Re-run validation (new round): resource readiness is re-checked from the start. */
  const reset = useCallback(() => {
    examActiveRef.current = false;
    setPhaseError(null);
    setPhase(ExamPhase.IDLE);
  }, []);

  const inRange = (from: ExamPhase) => phase >= from;

  return {
    phase,
    phaseLabel: EXAM_PHASE_LABELS[phase],
    phaseError:
      phaseError ??
      (phase === ExamPhase.VALIDATING_DEVTOOLS && isDevtoolsOpen
        ? "Please close developer tools before the exam can begin."
        : null),
    examActiveRef,
    isPermissionFlowActiveRef,
    shouldAcquireCamera: inRange(ExamPhase.VALIDATING_VIDEO),
    shouldAcquireAudio: inRange(ExamPhase.VALIDATING_AUDIO),
    shouldAcquireScreen: inRange(ExamPhase.VALIDATING_SCREEN_SHARE),
    shouldEnforceFullscreen: inRange(ExamPhase.VALIDATING_FULLSCREEN),
    setPhaseError,
    markPermissionFlowStart,
    markPermissionFlowEnd,
    reset,
  };
}
