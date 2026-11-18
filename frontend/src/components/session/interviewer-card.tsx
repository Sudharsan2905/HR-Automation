"use client";

import { useEffect, useRef } from "react";
import { Mic, User } from "lucide-react";

interface InterviewerCardProps {
  videoTrack: MediaStreamTrack | null;
  name: string;
  isSpeaking?: boolean;
}

export function InterviewerCard({ videoTrack, name, isSpeaking = false }: InterviewerCardProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoTrack && videoRef.current) {
      videoRef.current.srcObject = new MediaStream([videoTrack]);
    }
  }, [videoTrack]);

  const initial = name.charAt(0).toUpperCase();

  return (
    <div className="w-full h-full relative">
      {videoTrack ? (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />
      ) : (
        <div className="w-full h-full flex flex-col items-center justify-center gap-3">
          <div className={`h-16 w-16 rounded-full bg-white/10 flex items-center justify-center transition-shadow ${isSpeaking ? "shadow-[0_0_20px_rgba(52,211,153,0.5)]" : ""}`}>
            <span className="text-2xl font-semibold text-white/60">{initial}</span>
          </div>
          {isSpeaking ? (
            <div className="flex items-center gap-1.5 text-xs text-emerald-400">
              <Mic className="h-3 w-3 animate-pulse" />
              <SpeakingBars />
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-white/40">
              <User className="h-3 w-3" />
              <span>Panel</span>
            </div>
          )}
        </div>
      )}
      <span className="absolute bottom-3 left-3 text-sm font-medium text-white/40 tracking-wide bg-black/40 px-2.5 py-1 rounded-md z-10">
        {name}
      </span>
    </div>
  );
}

function SpeakingBars() {
  return (
    <>
      <div className="flex items-end gap-[2px] h-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className="w-[3px] rounded-full bg-emerald-400 speaking-bar"
            style={{ animationDelay: `${i * 120}ms` }}
          />
        ))}
      </div>
      <style>{`
        .speaking-bar {
          display: inline-block;
          height: 4px;
          animation: speakingBarWave 0.8s ease-in-out infinite;
        }
        @keyframes speakingBarWave {
          0%, 100% { height: 4px; }
          50% { height: 16px; }
        }
      `}</style>
    </>
  );
}
