"use client";

import { useEffect, useRef, type RefObject } from "react";
import { Mic } from "lucide-react";

/** Live mic level bars drawn from the shared AnalyserNode. */
export function AudioMonitor({
  analyserRef,
  active,
}: {
  analyserRef: RefObject<AnalyserNode | null>;
  active: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!active) return;
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      const analyser = analyserRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const bars = 24;
      const bw = canvas.width / bars;
      const data = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
      if (analyser && data) analyser.getByteFrequencyData(data);
      for (let i = 0; i < bars; i++) {
        const v = data ? data[Math.floor((i / bars) * data.length * 0.5)] / 255 : 0;
        const h = Math.max(2, v * canvas.height);
        ctx.fillStyle = v > 0.5 ? "#ef4444" : "#10b981";
        ctx.fillRect(i * bw + 1, canvas.height - h, bw - 2, h);
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active, analyserRef]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Mic className="size-3.5" /> Microphone
      </div>
      <canvas ref={canvasRef} width={240} height={40} className="w-full rounded-lg bg-muted" />
    </div>
  );
}
