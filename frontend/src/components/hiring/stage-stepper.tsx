"use client";

import { cn } from "@/lib/utils";
import { AlertCircle, Check, Clock, Loader2, PauseCircle } from "lucide-react";
import type { FlowStage, StageStatus } from "@/types/hiring";

const STYLE: Record<StageStatus, { ring: string; text: string }> = {
  pending: { ring: "border-zinc-200 bg-zinc-50 text-zinc-400", text: "text-muted-foreground" },
  waiting: { ring: "border-amber-300 bg-amber-50 text-amber-600", text: "text-amber-700" },
  running: { ring: "border-sky-300 bg-sky-50 text-sky-600", text: "text-sky-700" },
  done: { ring: "border-emerald-300 bg-emerald-50 text-emerald-600", text: "text-emerald-700" },
  failed: { ring: "border-red-300 bg-red-50 text-red-600", text: "text-red-700" },
};

function StageIcon({ status }: { status: StageStatus }) {
  const cls = "h-4 w-4";
  if (status === "done") return <Check className={cls} />;
  if (status === "running") return <Loader2 className={cn(cls, "animate-spin")} />;
  if (status === "failed") return <AlertCircle className={cls} />;
  if (status === "waiting") return <PauseCircle className={cls} />;
  return <Clock className={cls} />;
}

export function StageStepper({ stages }: { stages: FlowStage[] }) {
  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {stages.map((s, i) => {
        const st = STYLE[s.status] ?? STYLE.pending;
        return (
          <li key={s.key} className="relative rounded-lg border bg-card p-3">
            <div className="flex items-center gap-2">
              <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full border", st.ring)}>
                <StageIcon status={s.status} />
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">
                  <span className="mr-1 text-muted-foreground">{i + 1}.</span>{s.label}
                </p>
                <p className={cn("text-[11px] font-medium capitalize", st.text)}>{s.status}</p>
              </div>
            </div>
            {s.detail && <p className="mt-2 text-xs text-muted-foreground">{s.detail}</p>}
            {s.error && <p className="mt-2 whitespace-pre-wrap break-words text-xs text-red-600">{s.error}</p>}
          </li>
        );
      })}
    </ol>
  );
}
