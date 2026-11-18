"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

type AvatarMode = "speaking" | "listening" | "idle";

interface AIAvatarProps {
  mode: AvatarMode;
  analyserNode: AnalyserNode | null;
}

const BAR_COUNT = 72;
const INNER_RADIUS = 80;
const MAX_BAR_HEIGHT = 45;

export function AIAvatar({ mode, analyserNode }: AIAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);

  const isSpeaking = mode === "speaking";
  const isListening = mode === "listening";
  const isActive = isSpeaking || isListening;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const size = canvas.width;
    const cx = size / 2;
    const cy = size / 2;

    const draw = () => {
      ctx.clearRect(0, 0, size, size);

      const dataArray = new Uint8Array(BAR_COUNT);
      if (analyserNode) {
        const freqData = new Uint8Array(analyserNode.frequencyBinCount);
        analyserNode.getByteFrequencyData(freqData);
        const step = Math.floor(freqData.length / BAR_COUNT);
        for (let i = 0; i < BAR_COUNT; i++) {
          dataArray[i] = freqData[i * step];
        }
      }

      for (let i = 0; i < BAR_COUNT; i++) {
        const angle = (i / BAR_COUNT) * Math.PI * 2 - Math.PI / 2;
        const normalized = dataArray[i] / 255;
        const barHeight = isActive ? normalized * MAX_BAR_HEIGHT + 2 : 2;

        const x1 = cx + Math.cos(angle) * INNER_RADIUS;
        const y1 = cy + Math.sin(angle) * INNER_RADIUS;
        const x2 = cx + Math.cos(angle) * (INNER_RADIUS + barHeight);
        const y2 = cy + Math.sin(angle) * (INNER_RADIUS + barHeight);

        const alpha = isActive ? 0.4 + normalized * 0.6 : 0.15;
        if (isSpeaking) {
          ctx.strokeStyle = `rgba(0, 229, 255, ${alpha})`;
        } else if (isListening) {
          ctx.strokeStyle = `rgba(52, 211, 153, ${alpha})`;
        } else {
          ctx.strokeStyle = `rgba(0, 229, 255, 0.12)`;
        }

        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }

      if (isActive) {
        const gradient = ctx.createRadialGradient(cx, cy, INNER_RADIUS - 10, cx, cy, INNER_RADIUS + 15);
        gradient.addColorStop(0, isSpeaking ? "rgba(0,229,255,0.08)" : "rgba(52,211,153,0.08)");
        gradient.addColorStop(1, "transparent");
        ctx.beginPath();
        ctx.arc(cx, cy, INNER_RADIUS + 15, 0, Math.PI * 2);
        ctx.fillStyle = gradient;
        ctx.fill();
      }

      animFrameRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [analyserNode, isActive, isSpeaking, isListening]);

  return (
    <div className="flex flex-col items-center justify-center gap-3">
      <div className="relative w-[300px] h-[300px] flex items-center justify-center">
        <canvas
          ref={canvasRef}
          width={300}
          height={300}
          className="absolute inset-0"
        />
        <div
          className={cn(
            "w-[130px] h-[130px] rounded-full relative z-10",
            "bg-[radial-gradient(circle,#00e5ff_0%,#7c3aed_100%)]",
            !isActive && "animate-pulse"
          )}
          style={{
            boxShadow: isActive
              ? isSpeaking
                ? "0 0 50px rgba(0,229,255,0.5), 0 0 120px rgba(124,58,237,0.3)"
                : "0 0 50px rgba(52,211,153,0.4), 0 0 120px rgba(124,58,237,0.2)"
              : "0 0 25px rgba(0,229,255,0.25), 0 0 80px rgba(124,58,237,0.2)",
          }}
        />
      </div>
      <span className="text-sm font-medium text-white/40 tracking-wide">Suvera AI</span>
    </div>
  );
}
