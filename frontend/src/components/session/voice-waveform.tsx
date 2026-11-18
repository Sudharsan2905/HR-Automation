"use client";

import { useRef, useEffect, useCallback } from "react";
import { Mic } from "lucide-react";

interface VoiceWaveformProps {
  analyserNode: AnalyserNode | null;
  isRecording: boolean;
  label?: string;
}

const BAR_COUNT = 36;
const MIN_HEIGHT = 4;
const MAX_HEIGHT = 100;

export function VoiceWaveform({ analyserNode, isRecording, label = "You" }: VoiceWaveformProps) {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);
  const rafRef = useRef<number>(0);

  const animate = useCallback(() => {
    if (!analyserNode) return;
    const data = new Uint8Array(analyserNode.frequencyBinCount);
    analyserNode.getByteFrequencyData(data);

    const step = Math.floor(data.length / BAR_COUNT);
    for (let i = 0; i < BAR_COUNT; i++) {
      const bar = barsRef.current[i];
      if (!bar) continue;
      const value = data[i * step] / 255;
      const height = MIN_HEIGHT + value * (MAX_HEIGHT - MIN_HEIGHT);
      bar.style.height = `${height}px`;
    }

    rafRef.current = requestAnimationFrame(animate);
  }, [analyserNode]);

  useEffect(() => {
    if (analyserNode && isRecording) {
      rafRef.current = requestAnimationFrame(animate);
    } else if (isRecording) {
      // Fallback animation without analyser (remote participant speaking)
      const fallback = () => {
        const t = performance.now() / 1000;
        for (let i = 0; i < BAR_COUNT; i++) {
          const bar = barsRef.current[i];
          if (!bar) continue;
          const phase = t * 3 + i * 0.3;
          const val = (Math.sin(phase) * 0.5 + 0.5) * 0.5;
          bar.style.height = `${MIN_HEIGHT + val * (MAX_HEIGHT - MIN_HEIGHT)}px`;
        }
        rafRef.current = requestAnimationFrame(fallback);
      };
      rafRef.current = requestAnimationFrame(fallback);
    } else {
      cancelAnimationFrame(rafRef.current);
      // Reset bars to min height when idle
      barsRef.current.forEach((bar) => {
        if (bar) bar.style.height = `${MIN_HEIGHT}px`;
      });
    }
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyserNode, isRecording, animate]);

  return (
    <div className="w-full h-full relative flex flex-col items-center justify-center gap-5">
      <Mic className={`h-9 w-9 ${isRecording ? "text-emerald-400/70" : "text-white/25"} transition-colors`} />

      <div className="flex items-end justify-center gap-[3px] h-[100px]">
        {Array.from({ length: BAR_COUNT }, (_, i) => (
          <div
            key={i}
            ref={(el) => { barsRef.current[i] = el; }}
            className={`w-[4px] rounded-full transition-[height] duration-75 ${
              isRecording
                ? "bg-gradient-to-t from-emerald-400 to-cyan-400"
                : "bg-white/15 animate-pulse"
            }`}
            style={{
              height: `${MIN_HEIGHT}px`,
              animationDelay: isRecording ? undefined : `${(i % 5) * 150}ms`,
            }}
          />
        ))}
      </div>

      {label && (
        <span className="absolute bottom-3 left-3 text-sm font-medium text-white/40 tracking-wide bg-black/40 px-2.5 py-1 rounded-md">
          {label}
        </span>
      )}
    </div>
  );
}
