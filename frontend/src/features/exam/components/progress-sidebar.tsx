"use client";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { ExamAnswerMap, ExamQuestion, ExamRoundConfig } from "@/types/level1-exam";

export function ProgressSidebar({
  roundNumber,
  rounds,
  questions,
  currentIdx,
  answers,
  visited,
  onNavigate,
  className,
}: {
  roundNumber: number;
  rounds: ExamRoundConfig[];
  questions: ExamQuestion[];
  currentIdx: number;
  answers: ExamAnswerMap;
  visited: Set<string>;
  onNavigate: (idx: number) => void;
  className?: string;
}) {
  const answered = Object.keys(answers).length;
  const pct = (answered / questions.length) * 100;
  return (
    <div className={cn("space-y-5 p-4", className)}>
      <div className="space-y-2">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Assessment Progress
        </p>
        <p className="font-semibold">
          Round {roundNumber}
          {rounds.length > 0 ? ` of ${rounds.length}` : ""}
        </p>
        <Progress value={pct} />
        <div className="grid grid-cols-3 text-center text-xs">
          <div><div className="text-base font-semibold text-emerald-600">{answered}</div>Done</div>
          <div><div className="text-base font-semibold">{questions.length}</div>Total</div>
          <div><div className="text-base font-semibold text-amber-600">{questions.length - answered}</div>Left</div>
        </div>
      </div>

      {rounds.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Rounds</p>
          {rounds.map((r) => {
            const active = r.round_number === roundNumber;
            const done = r.round_number < roundNumber;
            return (
              <div key={r.round_number} className={cn("rounded-lg border p-2.5 text-sm", active && "border-primary")}>
                <div className="flex items-center justify-between">
                  <span className="font-medium">Round {r.round_number}</span>
                  <span className="text-xs text-muted-foreground">
                    {active ? "Active" : done ? "Done" : "Pending"}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {r.question_count} question{r.question_count === 1 ? "" : "s"}
                </p>
              </div>
            );
          })}
        </div>
      ) : null}

      <div className="space-y-2">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Questions — Round {roundNumber}
        </p>
        <div className="grid grid-cols-5 gap-2">
          {questions.map((q, i) => {
            const state =
              i === currentIdx ? "active" : answers[q.id] !== undefined ? "answered" : visited.has(q.id) ? "visited" : "default";
            return (
              <button
                key={q.id}
                type="button"
                onClick={() => onNavigate(i)}
                className={cn(
                  "h-9 rounded-md border text-sm font-medium transition-colors",
                  state === "active" && "border-primary bg-primary text-primary-foreground",
                  state === "answered" && "border-emerald-500 bg-emerald-500/15 text-emerald-700",
                  state === "visited" && "border-amber-500 bg-amber-500/15 text-amber-700",
                  state === "default" && "hover:bg-muted"
                )}
              >
                {i + 1}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span>Green: answered</span>
          <span>Amber: visited</span>
          <span>Blue: current</span>
        </div>
      </div>
    </div>
  );
}
