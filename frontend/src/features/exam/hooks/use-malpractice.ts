"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";
import { flagExamMalpractice } from "@/lib/api/level1-exam";
import { useExamStore } from "@/stores/exam-store";
import type { ExamMonitoringConfig, MalpracticeType } from "@/types/level1-exam";
import { MALPRACTICE_LIMIT, TWO_STRIKE_TYPES, VIOLATION_MESSAGES } from "../lib/constants";

export interface ViolationPayload {
  type: MalpracticeType;
  description?: string;
}

async function snapshotVideoFrame(video: HTMLVideoElement | null | undefined) {
  if (!video || video.videoWidth === 0) return null;
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0);
  return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
}

/**
 * Reports violations to the backend (with screen + face evidence stills), updates the
 * zustand proctoring store, and signals the terminal state. Video/audio clip evidence
 * (LiveKit/MediaRecorder) is not ported; stills are uploaded instead.
 */
export function useMalpractice({
  submissionId,
  monitoringConfig,
  onTerminated,
  videoRef,
  captureScreenFrame,
}: {
  submissionId: string;
  monitoringConfig: Partial<ExamMonitoringConfig>;
  onTerminated?: (reason: string) => void;
  videoRef?: RefObject<HTMLVideoElement | null>;
  captureScreenFrame?: () => Promise<Blob | null>;
}) {
  const firstWarned = useRef<Partial<Record<MalpracticeType, boolean>>>({});
  const cfgRef = useRef(monitoringConfig);
  useEffect(() => {
    cfgRef.current = monitoringConfig;
  });

  const flagViolation = useCallback(
    async (event: ViolationPayload): Promise<void> => {
      const store = useExamStore.getState();
      const cfg = cfgRef.current;

      if (TWO_STRIKE_TYPES.has(event.type) && !firstWarned.current[event.type]) {
        firstWarned.current[event.type] = true;
        store.setLastViolation(event.type, `Warning: ${VIOLATION_MESSAGES[event.type]}`);
        return;
      }

      const [screenImage, faceImage] = await Promise.all([
        cfg.screenshot_enabled && captureScreenFrame ? captureScreenFrame() : null,
        cfg.video_monitoring ? snapshotVideoFrame(videoRef?.current) : null,
      ]);

      const fd = new FormData();
      fd.append("type", event.type);
      fd.append("description", event.description ?? VIOLATION_MESSAGES[event.type] ?? "");
      if (screenImage) fd.append("screen_image", screenImage, "screen.jpg");
      if (faceImage) fd.append("face_image", faceImage, "face.jpg");

      try {
        const data = await flagExamMalpractice(submissionId, fd);
        if (data?.malpractice_count !== undefined) store.setMalpracticeCount(data.malpractice_count);
        if (data?.is_terminal) {
          store.setTerminated(event.type);
          onTerminated?.(event.type);
        } else {
          store.setLastViolation(
            event.type,
            `Warning ${String(data?.malpractice_count)}/${MALPRACTICE_LIMIT}: ${VIOLATION_MESSAGES[event.type]}`
          );
        }
      } catch (err) {
        console.warn("Malpractice flag failed:", err);
      }
    },
    [submissionId, onTerminated, videoRef, captureScreenFrame]
  );

  return { flagViolation };
}
