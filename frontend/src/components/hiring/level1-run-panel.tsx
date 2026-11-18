"use client";

import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { AlertCircle, Check, Clock, Loader2, Play } from "lucide-react";
import type { FlowEvent, FlowStep, HiringFlow } from "@/types/hiring";

const STEP_BADGE: Record<string, string> = {
  pending: "bg-zinc-100 text-zinc-700",
  waiting: "bg-amber-100 text-amber-800",
  running: "bg-sky-100 text-sky-800",
  done: "bg-emerald-100 text-emerald-800",
  completed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  skipped: "bg-zinc-100 text-zinc-500",
};

function StepIcon({ status }: { status: string }) {
  const cls = "h-4 w-4";
  if (status === "done" || status === "completed") return <Check className={cn(cls, "text-emerald-600")} />;
  if (status === "running") return <Loader2 className={cn(cls, "animate-spin text-sky-600")} />;
  if (status === "failed") return <AlertCircle className={cn(cls, "text-red-600")} />;
  return <Clock className={cn(cls, "text-zinc-400")} />;
}

function Step({ step }: { step: FlowStep }) {
  const total = step.progress?.total ?? 0;
  const pct = total > 0 ? Math.round(((step.progress?.done ?? 0) / total) * 100) : null;
  return (
    <li className="rounded-lg border p-3">
      <div className="flex items-start gap-3">
        <div className="mt-0.5"><StepIcon status={step.status} /></div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">{step.title}</p>
            <Badge variant="secondary" className={STEP_BADGE[step.status] || STEP_BADGE.pending}>{step.status}</Badge>
            <span className="text-[11px] text-muted-foreground">{step.agent}</span>
          </div>
          <p className="text-xs text-muted-foreground">{step.description}</p>
          {pct !== null && (
            <div className="flex items-center gap-2">
              <Progress value={pct} className="h-1.5" />
              <span className="shrink-0 text-[11px] text-muted-foreground">{step.progress?.done}/{total}</span>
            </div>
          )}
          {step.detail && <p className="text-xs">{step.detail}</p>}
          {step.error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
              <p className="font-medium">{step.error.message}</p>
              {step.error.detail && <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px]">{step.error.detail}</p>}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

const LEVEL_COLOR: Record<string, string> = {
  info: "text-muted-foreground",
  warn: "text-amber-600",
  error: "text-red-600",
};

export function ActivityFeed({ flow }: { flow: HiringFlow }) {
  const rows = useMemo(() => {
    const l1: FlowEvent[] = (flow.level1_run?.events ?? []).map((e) => ({
      ts: e.ts, stage: `level1 · ${e.step}`, level: (e.level as FlowEvent["level"]) || "info", message: e.message,
    }));
    return [...flow.events, ...l1]
      .sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0))
      .slice(0, 300);
  }, [flow]);

  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">Live activity</CardTitle></CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing yet.</p>
        ) : (
          <ScrollArea className="h-64 pr-3">
            <ul className="space-y-1.5">
              {rows.map((e, i) => (
                <li key={`${e.ts}-${i}`} className="flex gap-2 text-xs">
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {new Date(e.ts).toLocaleTimeString()}
                  </span>
                  <span className="shrink-0 rounded bg-muted px-1.5 text-[10px] uppercase text-muted-foreground">{e.stage}</span>
                  <span className={cn("min-w-0 break-words", LEVEL_COLOR[e.level] || "")}>{e.message}</span>
                </li>
              ))}
            </ul>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

export function Level1RunPanel({ flow, starting, onStart }: {
  flow: HiringFlow;
  starting: boolean;
  onStart: () => void;
}) {
  const run = flow.level1_run;
  const active = run?.status === "running";
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
        <CardTitle className="text-base">
          Level 1 pipeline
          {run?.status && <Badge variant="secondary" className={cn("ml-2", STEP_BADGE[run.status] || "")}>{run.status}</Badge>}
        </CardTitle>
        <Button size="sm" variant="outline" onClick={onStart} disabled={starting || active}>
          {starting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
          {run ? "Re-run for selected profiles" : "Start Level 1"}
        </Button>
      </CardHeader>
      <CardContent>
        {!run || run.steps.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Level 1 starts automatically once profiles are shortlisted. You can also start it manually.
          </p>
        ) : (
          <ul className="space-y-2">{run.steps.map((s) => <Step key={s.key} step={s} />)}</ul>
        )}
      </CardContent>
    </Card>
  );
}
