"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ExamRoundConfig } from "@/types/level1-exam";
import { ExamDialog } from "./exam-dialog";

export function RoundInstructions({
  open,
  roundNumber,
  roundConfig,
  totalRounds,
  onStart,
  ctaLabel = "Let Me In",
}: {
  open: boolean;
  roundNumber: number;
  roundConfig: ExamRoundConfig;
  totalRounds: number;
  onStart: () => void;
  ctaLabel?: string;
}) {
  const h = Math.floor(roundConfig.max_duration_minutes / 60);
  const m = roundConfig.max_duration_minutes % 60;
  const duration = h > 0 ? `${h}h ${m > 0 ? `${m}m` : ""}` : `${m} minutes`;
  const rules = [
    "Answer all questions before the timer runs out.",
    "You can navigate between questions freely before submitting.",
    "Once you submit this round you cannot go back.",
    "Ensure a stable internet connection before starting.",
    "Remain in fullscreen mode for the entire duration.",
    "Do not switch tabs, applications, or browser windows.",
    "Enable Do Not Disturb to prevent notification interruptions.",
    "Camera and microphone (if required) must remain active.",
  ];
  return (
    <ExamDialog
      open={open}
      mandatory
      title={`Round ${roundNumber} — Instructions`}
      className="sm:max-w-lg"
      footer={
        <Button className="w-full" onClick={onStart}>
          {ctaLabel}
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="flex items-center justify-center gap-3">
          {Array.from({ length: totalRounds }, (_, i) => i + 1).map((n) => (
            <div key={n} className="flex flex-col items-center gap-1">
              <div
                className={cn(
                  "flex size-7 items-center justify-center rounded-full border text-xs font-semibold",
                  n < roundNumber && "border-emerald-500 bg-emerald-500 text-white",
                  n === roundNumber && "border-primary bg-primary text-primary-foreground",
                  n > roundNumber && "text-muted-foreground"
                )}
              >
                {n < roundNumber ? "✓" : n}
              </div>
              <span className="text-[10px]">Round {n}</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-3 divide-x rounded-lg border text-center">
          {[
            [String(roundConfig.question_count), "Questions"],
            [duration, "Time Limit"],
            [`${roundNumber}/${totalRounds}`, "Round"],
          ].map(([v, l]) => (
            <div key={l} className="py-3">
              <div className="text-base font-semibold text-foreground">{v}</div>
              <div className="text-xs">{l}</div>
            </div>
          ))}
        </div>
        <ul className="list-disc space-y-1 pl-5">
          {rules.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <p className="text-xs italic">
          Stay focused and give your best. This assessment is monitored for integrity and fairness.
        </p>
      </div>
    </ExamDialog>
  );
}
