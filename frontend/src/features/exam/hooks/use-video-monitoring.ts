"use client";

import { useEffect, useRef, type RefObject } from "react";
import type { MalpracticeType } from "@/types/level1-exam";

const DETECTION_INTERVAL_MS = 700;
const FACE_ABSENCE_THRESHOLD_MS = 3_000;
const VIOLATION_COOLDOWN_MS = 15_000;
const MIN_DETECTION_CONFIDENCE = 0.55;
// Served from /public so the strict exam does not depend on a third-party CDN.
const MEDIAPIPE_WASM = "/mediapipe/wasm";
const FACE_MODEL = "/mediapipe/blaze_face_short_range.tflite";

/** Face presence / multi-face detection via MediaPipe. Fails silently if the model can't load. */
export function useVideoMonitoring({
  enabled,
  videoRef,
  onViolation,
}: {
  enabled: boolean;
  videoRef: RefObject<HTMLVideoElement | null>;
  onViolation: (type: MalpracticeType, description: string) => void;
}) {
  const cb = useRef(onViolation);
  useEffect(() => {
    cb.current = onViolation;
  });

  useEffect(() => {
    if (!enabled) return;
    let running = true;
    let raf = 0;
    let detector: {
      detectForVideo: (v: HTMLVideoElement, t: number) => { detections: unknown[] };
      close?: () => void;
    } | null = null;
    let lastDetection = 0;
    let absenceStart: number | null = null;
    const lastFlag: Partial<Record<MalpracticeType, number>> = {};

    const canFlag = (type: MalpracticeType) => {
      const now = performance.now();
      if (now - (lastFlag[type] ?? 0) > VIOLATION_COOLDOWN_MS) {
        lastFlag[type] = now;
        return true;
      }
      return false;
    };

    const step = () => {
      if (!running) return;
      const now = performance.now();
      if (now - lastDetection >= DETECTION_INTERVAL_MS) {
        lastDetection = now;
        const video = videoRef.current;
        if (video && video.readyState >= 2 && detector) {
          try {
            const count = detector.detectForVideo(video, now).detections?.length ?? 0;
            if (count === 0) {
              if (absenceStart === null) absenceStart = now;
              else if (now - absenceStart > FACE_ABSENCE_THRESHOLD_MS && canFlag("face_absence")) {
                cb.current(
                  "face_absence",
                  `No face detected in camera feed for ${Math.round((now - absenceStart) / 1000)} seconds`
                );
                absenceStart = null;
              }
            } else {
              absenceStart = null;
            }
            if (count > 1 && canFlag("multiple_faces")) {
              cb.current("multiple_faces", `Multiple faces (${count}) detected in camera feed`);
            }
          } catch {
            /* first frames may fail */
          }
        }
      }
      raf = requestAnimationFrame(step);
    };

    void (async () => {
      try {
        const { FaceDetector, FilesetResolver } = await import("@mediapipe/tasks-vision");
        const vision = await FilesetResolver.forVisionTasks(MEDIAPIPE_WASM);
        const create = (delegate: "GPU" | "CPU") =>
          FaceDetector.createFromOptions(vision, {
            baseOptions: { modelAssetPath: FACE_MODEL, delegate },
            runningMode: "VIDEO",
            minDetectionConfidence: MIN_DETECTION_CONFIDENCE,
          });
        const d = await create("GPU").catch(() => create("CPU"));
        if (!running) {
          d.close();
          return;
        }
        detector = d;
        raf = requestAnimationFrame(step);
      } catch {
        /* MediaPipe unavailable — skip face monitoring */
      }
    })();

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      detector?.close?.();
    };
  }, [enabled, videoRef]);
}
