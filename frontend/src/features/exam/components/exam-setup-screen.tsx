"use client";

import { Check, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ExamMonitoringConfig } from "@/types/level1-exam";
import { ExamPhase } from "../hooks/use-exam-orchestrator";

interface Step {
  phase: ExamPhase;
  label: string;
  active: (c: Partial<ExamMonitoringConfig>) => boolean;
}

const STEPS: Step[] = [
  { phase: ExamPhase.VALIDATING_NETWORK, label: "Network connectivity", active: () => true },
  { phase: ExamPhase.VALIDATING_DEVTOOLS, label: "Developer tools closed", active: (c) => !!c.tab_monitoring },
  { phase: ExamPhase.VALIDATING_VIDEO, label: "Camera access", active: (c) => !!c.video_monitoring },
  { phase: ExamPhase.VALIDATING_AUDIO, label: "Microphone access", active: (c) => !!c.audio_monitoring },
  {
    phase: ExamPhase.VALIDATING_SCREEN_SHARE,
    label: "Screen sharing",
    active: (c) => !!(c.tab_monitoring || c.screenshot_enabled),
  },
  { phase: ExamPhase.VALIDATING_FULLSCREEN, label: "Fullscreen mode", active: (c) => !!c.tab_monitoring },
];

export function ExamSetupScreen({
  phase,
  phaseLabel,
  phaseError,
  config,
  onShareScreen,
  onRequestFullscreen,
  onRetryCamera,
  onRetryAudio,
}: {
  phase: ExamPhase;
  phaseLabel: string;
  phaseError: string | null;
  config: Partial<ExamMonitoringConfig>;
  onShareScreen: () => void;
  onRequestFullscreen: () => void;
  onRetryCamera: () => void;
  onRetryAudio: () => void;
}) {
  const steps = STEPS.filter((s) => s.active(config));

  const action = (() => {
    if (phase === ExamPhase.VALIDATING_SCREEN_SHARE)
      return <Button onClick={onShareScreen}>Share Entire Screen</Button>;
    if (phase === ExamPhase.VALIDATING_FULLSCREEN)
      return <Button onClick={onRequestFullscreen}>Enter Fullscreen</Button>;
    if (phase === ExamPhase.VALIDATING_VIDEO && phaseError)
      return <Button onClick={onRetryCamera}>Retry Camera</Button>;
    if (phase === ExamPhase.VALIDATING_AUDIO && phaseError)
      return <Button onClick={onRetryAudio}>Retry Microphone</Button>;
    return null;
  })();

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-6">
      <div className="w-full max-w-md rounded-xl border bg-background p-8 shadow-sm">
        <h1 className="text-lg font-semibold">Setting up your exam environment</h1>
        <p className="mt-1 text-sm text-muted-foreground">{phaseLabel}</p>
        <ol className="mt-6 space-y-3">
          {steps.map((s) => {
            const done = phase > s.phase;
            const current = phase === s.phase;
            const error = current && !!phaseError;
            return (
              <li key={s.phase} className="flex items-center gap-3 text-sm">
                <span
                  className={cn(
                    "flex size-6 items-center justify-center rounded-full border",
                    done && "border-emerald-500 bg-emerald-500 text-white",
                    error && "border-destructive text-destructive",
                    current && !error && "border-primary text-primary"
                  )}
                >
                  {done ? (
                    <Check className="size-3.5" />
                  ) : error ? (
                    <AlertCircle className="size-3.5" />
                  ) : current ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : null}
                </span>
                <span className={cn(!done && !current && "text-muted-foreground")}>{s.label}</span>
              </li>
            );
          })}
        </ol>
        {phaseError ? (
          <p className="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">{phaseError}</p>
        ) : null}
        {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
      </div>
    </div>
  );
}
