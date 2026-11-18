"use client";

import type { RefObject } from "react";
import { cn } from "@/lib/utils";
import type { ExamMonitoringConfig, ExamNetworkStatus } from "@/types/level1-exam";
import { AudioMonitor } from "./audio-monitor";
import { VideoMonitor } from "./video-monitor";

function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium",
        ok ? "bg-emerald-500/10 text-emerald-700" : "bg-amber-500/10 text-amber-700"
      )}
    >
      <span className={cn("size-1.5 rounded-full", ok ? "bg-emerald-500" : "bg-amber-500")} />
      {children}
    </div>
  );
}

export function TimerCard({
  hh,
  mm,
  ss,
  low,
  paused,
}: {
  hh: string;
  mm: string;
  ss: string;
  low: boolean;
  paused: boolean;
}) {
  return (
    <div className={cn("rounded-xl border p-4", low && "border-destructive bg-destructive/5")}>
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Time Remaining{paused ? " (paused)" : ""}
      </p>
      <div className={cn("mt-2 flex items-center justify-center gap-2 font-mono text-3xl font-semibold", low && "text-destructive")}>
        {[hh, mm, ss].map((v, i) => (
          <span key={i} className="flex items-center gap-2">
            {i > 0 ? <span>:</span> : null}
            <span>{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function MonitoringPanel({
  config,
  isScreenCapturing,
  networkStatus,
  videoRef,
  bindVideo,
  analyserRef,
  audioActive,
  onFaceWarning,
}: {
  config: Partial<ExamMonitoringConfig>;
  isScreenCapturing: boolean;
  networkStatus: ExamNetworkStatus;
  videoRef: RefObject<HTMLVideoElement | null>;
  bindVideo: (el: HTMLVideoElement | null) => void;
  analyserRef: RefObject<AnalyserNode | null>;
  audioActive: boolean;
  onFaceWarning: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Monitoring</p>
        {config.video_monitoring ? <Badge ok>Camera Active</Badge> : null}
        {config.audio_monitoring ? <Badge ok>Mic Active</Badge> : null}
        {config.screenshot_enabled ? (
          <Badge ok={isScreenCapturing}>
            {isScreenCapturing ? "Screen Capture Active" : "Screen Capture Inactive"}
          </Badge>
        ) : null}
        <Badge ok={networkStatus === "connected"}>
          {networkStatus === "connected"
            ? "Network Stable"
            : networkStatus === "on_hold"
              ? "Session Paused"
              : "Reconnecting…"}
        </Badge>
      </div>
      {config.video_monitoring ? <VideoMonitor videoRef={videoRef} bindVideo={bindVideo} onWarning={onFaceWarning} /> : null}
      {config.audio_monitoring ? <AudioMonitor analyserRef={analyserRef} active={audioActive} /> : null}
    </div>
  );
}
