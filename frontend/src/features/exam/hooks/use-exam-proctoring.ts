"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { uploadExamScreenshot } from "@/lib/api/level1-exam";
import type { ExamMonitoringConfig, MalpracticeType } from "@/types/level1-exam";
import { takeCameraStream } from "../lib/stream-store";
import { useAudioMonitoring } from "./use-audio-monitoring";
import { useDevtoolsMonitoring } from "./use-devtools-monitoring";
import { useFullscreenEnforcement } from "./use-fullscreen-enforcement";
import { useTabMonitoring } from "./use-tab-monitoring";
import { useVideoMonitoring } from "./use-video-monitoring";

/** Tracks document.fullscreenElement. */
export function useIsFullscreen() {
  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setIsFullscreen(!!document.fullscreenElement);
    sync();
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("webkitfullscreenchange", sync);
    };
  }, []);
  return isFullscreen;
}

interface Options {
  config: Partial<ExamMonitoringConfig>;
  submissionId: string;
  gates: { camera: boolean; audio: boolean; fullscreen: boolean };
  examActiveRef: RefObject<boolean>;
  isPermissionFlowActiveRef: RefObject<boolean>;
  isScreenCapturing: boolean;
  captureFrame: () => Promise<Blob | null>;
  flagViolation: (type: MalpracticeType, description?: string) => void;
  onCameraError: (message: string) => void;
  onFullscreenBlocked: () => void;
}

/**
 * Wires every proctoring signal: camera stream, audio level, face detection, tab/focus,
 * devtools, fullscreen exit and periodic screenshots.
 */
export function useExamProctoring(o: Options) {
  const { config, gates, flagViolation, examActiveRef } = o;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const [isCameraReady, setIsCameraReady] = useState(false);
  const [isAudioReady, setIsAudioReady] = useState(false);
  const [cameraAttempt, setCameraAttempt] = useState(0);
  const onCameraErrorRef = useRef(o.onCameraError);
  const onFsBlockedRef = useRef(o.onFullscreenBlocked);
  useEffect(() => {
    onCameraErrorRef.current = o.onCameraError;
    onFsBlockedRef.current = o.onFullscreenBlocked;
  });

  // Camera
  useEffect(() => {
    if (!config.video_monitoring || !gates.camera) return;
    let cancelled = false;
    void (async () => {
      const stored = takeCameraStream();
      let stream: MediaStream;
      try {
        stream = stored ?? (await navigator.mediaDevices.getUserMedia({ video: true }));
      } catch {
        onCameraErrorRef.current("Camera access was denied. Please allow camera permission and retry.");
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      cameraStreamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setIsCameraReady(true);
    })();
    return () => {
      cancelled = true;
      cameraStreamRef.current?.getTracks().forEach((t) => t.stop());
      cameraStreamRef.current = null;
      setIsCameraReady(false);
    };
  }, [config.video_monitoring, gates.camera, cameraAttempt]);

  /** Bind the stream to the <video> once the active UI mounts it. */
  const bindCamera = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el;
    if (el && cameraStreamRef.current && el.srcObject !== cameraStreamRef.current) {
      el.srcObject = cameraStreamRef.current;
      el.play().catch(() => undefined);
    }
  }, []);

  const retryCamera = useCallback(() => setCameraAttempt((n) => n + 1), []);

  // Audio
  const [audioAttempt, setAudioAttempt] = useState(0);
  useAudioMonitoring({
    enabled: (config.audio_monitoring ?? false) && audioAttempt >= 0,
    shouldInitialize: gates.audio,
    analyserRef,
    onStreamReady: useCallback(() => setIsAudioReady(true), []),
    onViolation: useCallback(
      (description: string) => flagViolation("audio_violation", description),
      [flagViolation]
    ),
  });
  const retryAudio = useCallback(() => setAudioAttempt((n) => n + 1), []);

  // Face detection
  useVideoMonitoring({
    enabled: config.video_monitoring ?? false,
    videoRef,
    onViolation: flagViolation,
  });

  // Devtools + tab
  useDevtoolsMonitoring({
    enabled: config.tab_monitoring ?? false,
    examActiveRef,
    onViolation: useCallback(
      (d: string) => flagViolation("devtools_open", d),
      [flagViolation]
    ),
  });
  useTabMonitoring({
    enabled: config.tab_monitoring ?? false,
    examActiveRef,
    isPermissionFlowActiveRef: o.isPermissionFlowActiveRef,
    onTabSwitch: useCallback((d: string) => flagViolation("tab_switch", d), [flagViolation]),
    onFocusViolation: useCallback(
      (d: string) => flagViolation("notification_received", d),
      [flagViolation]
    ),
  });

  // Fullscreen
  const { requestFullscreen } = useFullscreenEnforcement({
    enabled: gates.fullscreen,
    onBlockRequired: useCallback(() => {
      if (examActiveRef.current) onFsBlockedRef.current();
    }, [examActiveRef]),
    onExit: useCallback(
      (description: string) => {
        if (!examActiveRef.current) return;
        onFsBlockedRef.current();
        flagViolation("fullscreen_exit", description);
      },
      [examActiveRef, flagViolation]
    ),
  });

  // Periodic screenshots
  const { submissionId, isScreenCapturing, captureFrame } = o;
  useEffect(() => {
    if (!config.screenshot_enabled || !isScreenCapturing) return;
    const ms = (config.screenshot_interval_seconds ?? 30) * 1000;
    const id = setInterval(() => {
      void (async () => {
        try {
          const blob = await captureFrame();
          if (blob) await uploadExamScreenshot(submissionId, blob);
        } catch {
          /* silent */
        }
      })();
    }, ms);
    return () => clearInterval(id);
  }, [config.screenshot_enabled, config.screenshot_interval_seconds, isScreenCapturing, captureFrame, submissionId]);

  return {
    videoRef,
    bindCamera,
    analyserRef,
    isCameraReady,
    isAudioReady,
    retryCamera,
    retryAudio,
    requestFullscreen,
  };
}
