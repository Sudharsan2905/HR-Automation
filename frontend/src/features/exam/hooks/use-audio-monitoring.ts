"use client";

import { useEffect, useRef, type RefObject } from "react";
import { takeAudioStream } from "../lib/stream-store";

const COOLDOWN_MS = 30_000;
const THRESHOLD = 20;
const SUSTAINED_S = 5;

/** Mic level monitor: flags sustained noise above a threshold; exposes an AnalyserNode. */
export function useAudioMonitoring({
  enabled,
  shouldInitialize,
  analyserRef,
  onStreamReady,
  onViolation,
}: {
  enabled: boolean;
  shouldInitialize: boolean;
  analyserRef: RefObject<AnalyserNode | null>;
  onStreamReady?: (stream: MediaStream) => void;
  onViolation: (description: string) => void;
}) {
  const violationCb = useRef(onViolation);
  const readyCb = useRef(onStreamReady);
  useEffect(() => {
    violationCb.current = onViolation;
    readyCb.current = onStreamReady;
  });

  useEffect(() => {
    if (!enabled || !shouldInitialize) return;
    let cancelled = false;
    let raf: number | null = null;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;

    void (async () => {
      try {
        const stored = takeAudioStream();
        const s = stored ?? (await navigator.mediaDevices.getUserMedia({ audio: true }));
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        stream = s;
        readyCb.current?.(s);
        ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        ctx.createMediaStreamSource(s).connect(analyser);
        analyserRef.current = analyser;

        const data = new Uint8Array(analyser.frequencyBinCount);
        let start: number | null = null;
        let lastFired: number | null = null;

        const tick = () => {
          if (cancelled) return;
          analyser.getByteFrequencyData(data);
          let sum = 0;
          for (const v of data) sum += v;
          const avg = sum / data.length;
          const now = performance.now();
          if (avg > THRESHOLD) {
            if (start === null) start = now;
            else if ((now - start) / 1000 >= SUSTAINED_S) {
              if (lastFired === null || now - lastFired >= COOLDOWN_MS) {
                lastFired = now;
                start = null;
                violationCb.current(
                  `Sustained background noise detected above threshold for ${SUSTAINED_S} seconds`
                );
              }
            }
          } else {
            start = null;
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      } catch {
        /* microphone denied — setup screen keeps waiting */
      }
    })();

    return () => {
      cancelled = true;
      if (raf !== null) cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      void ctx?.close();
      analyserRef.current = null;
    };
  }, [enabled, shouldInitialize, analyserRef]);
}
