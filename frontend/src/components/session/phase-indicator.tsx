"use client";

interface PhaseIndicatorProps {
  speaking: boolean;
  listening: boolean;
  paused: boolean;
}

export function PhaseIndicator({ speaking, listening, paused }: PhaseIndicatorProps) {
  if (paused) {
    return (
      <div className="flex items-center gap-2 text-sm text-white/70">
        <span className="w-2 h-2 rounded-full bg-amber-400" />
        <span>Paused</span>
      </div>
    );
  }

  if (speaking) {
    return (
      <div className="flex items-center gap-2 text-sm text-white/70">
        <span className="w-2 h-2 rounded-full bg-[#00e5ff] animate-pulse" />
        <span>Speaking...</span>
      </div>
    );
  }

  if (listening) {
    return (
      <div className="flex items-center gap-2 text-sm text-white/70">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span>Listening...</span>
      </div>
    );
  }

  return null;
}
