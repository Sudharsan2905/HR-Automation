"use client";

import { RefObject } from "react";

interface CameraPipProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  active: boolean;
}

export function CameraPip({ videoRef, active }: CameraPipProps) {
  return (
    <div className="w-full h-full relative">
      {active ? (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-sm text-white/50">
          Camera off
        </div>
      )}
      <span className="absolute bottom-3 left-3 text-sm font-medium text-white/40 tracking-wide bg-black/40 px-2.5 py-1 rounded-md">
        You
      </span>
    </div>
  );
}
