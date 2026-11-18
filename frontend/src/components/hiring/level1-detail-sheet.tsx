"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { getLevel1Submission } from "@/lib/api/hiring";
import { cn } from "@/lib/utils";
import { CheckCircle2, Loader2, ShieldAlert, XCircle } from "lucide-react";
import type {
  FlowCandidate, Level1MalpracticeEvent, Level1QuestionReview, Level1SubmissionReview,
} from "@/types/hiring";

type Option = string | { id?: string; text?: string; label?: string };

const optText = (o: Option) => (typeof o === "string" ? o : o.text ?? o.label ?? o.id ?? "");
const optId = (o: Option) => (typeof o === "string" ? o : o.id ?? "");

function asText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.map(asText).join(", ");
  return JSON.stringify(v, null, 2);
}

function answerSet(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => String(x));
  if (v === null || v === undefined || v === "") return [];
  return [String(v)];
}

function eventLabel(e: Level1MalpracticeEvent) {
  return [e.type ?? e.event_type, e.message ?? e.detail].filter(Boolean).join(": ");
}

function Question({ q, index }: { q: Level1QuestionReview; index: number }) {
  const options = (q.options ?? []) as Option[];
  const given = answerSet(q.candidate_answer);
  const correct = answerSet(q.correct_answer);
  const isEssay = options.length === 0;
  const hit = (o: Option, set: string[]) => set.includes(optId(o)) || set.includes(optText(o));
  return (
    <li className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Q{index + 1}</span>
        {q.question_type && <Badge variant="outline">{q.question_type.replace(/_/g, " ")}</Badge>}
        {q.is_correct === true && <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> Correct</span>}
        {q.is_correct === false && <span className="inline-flex items-center gap-1 text-xs text-red-600"><XCircle className="h-3.5 w-3.5" /> Incorrect</span>}
        {q.score != null && q.max_score != null && (
          <span className="ml-auto text-xs text-muted-foreground">{q.score}/{q.max_score}</span>
        )}
      </div>
      <p className="whitespace-pre-wrap text-sm">{q.question_text}</p>

      {!isEssay && (
        <ul className="space-y-1">
          {options.map((o, i) => {
            const chosen = hit(o, given);
            const right = hit(o, correct);
            return (
              <li
                key={i}
                className={cn(
                  "rounded-md border px-2 py-1 text-sm",
                  right && "border-emerald-300 bg-emerald-50",
                  chosen && !right && "border-red-300 bg-red-50",
                )}
              >
                {optText(o)}
                {chosen && <span className="ml-2 text-[11px] font-medium text-muted-foreground">candidate&apos;s answer</span>}
                {right && <span className="ml-2 text-[11px] font-medium text-emerald-700">correct</span>}
              </li>
            );
          })}
        </ul>
      )}

      {isEssay && (
        <div className="space-y-2">
          <div>
            <p className="text-xs font-medium text-muted-foreground">Candidate answer</p>
            <p className="whitespace-pre-wrap rounded-md bg-muted/50 p-2 text-sm">{asText(q.candidate_answer) || "No answer"}</p>
          </div>
          {asText(q.correct_answer) && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">Expected answer</p>
              <p className="whitespace-pre-wrap rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm">{asText(q.correct_answer)}</p>
            </div>
          )}
        </div>
      )}

      {q.feedback && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Evaluation feedback</p>
          <p className="whitespace-pre-wrap text-sm">{q.feedback}</p>
        </div>
      )}
      {q.malpractice_events && q.malpractice_events.length > 0 && (
        <p className="text-xs text-amber-700">Flags: {q.malpractice_events.map(eventLabel).join(" | ")}</p>
      )}
    </li>
  );
}

export function Level1DetailSheet({ candidate, fallbackAssessmentId, onClose }: {
  candidate: FlowCandidate | null;
  fallbackAssessmentId?: string | null;
  onClose: () => void;
}) {
  const [result, setResult] = useState<{ key: string; data?: Level1SubmissionReview; error?: string } | null>(null);

  const submissionId = candidate?.level1.submission_id ?? null;
  const assessmentId = candidate?.level1.assessment_id ?? fallbackAssessmentId ?? null;
  const key = submissionId && assessmentId ? `${assessmentId}:${submissionId}` : "";

  useEffect(() => {
    if (!key || !assessmentId || !submissionId) return;
    let live = true;
    getLevel1Submission(assessmentId, submissionId)
      .then((d) => { if (live) setResult({ key, data: d }); })
      .catch((e: { message?: string }) => { if (live) setResult({ key, error: e?.message || "Could not load the submission" }); });
    return () => { live = false; };
  }, [key, assessmentId, submissionId]);

  const current = result && result.key === key ? result : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;
  const loading = !!key && !current;

  const questions = data?.questions ?? data?.answers ?? [];
  const events = [...(data?.malpractice_events ?? []), ...(data?.events ?? [])];
  const pct = data?.percentage ?? candidate?.level1.percentage ?? null;

  return (
    <Sheet open={!!candidate} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{candidate?.name} · Level 1</SheetTitle>
          <SheetDescription>
            {pct != null ? `Score ${Math.round(pct * 10) / 10}%` : "Per-question answers and evaluation"}
            {candidate?.level1.status ? ` · ${candidate.level1.status.replace(/_/g, " ")}` : ""}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          {!assessmentId && submissionId && (
            <p className="text-sm text-amber-700">The assessment id for this submission was not provided by the server.</p>
          )}
          {loading && <p className="inline-flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>}
          {error && <p className="whitespace-pre-wrap text-sm text-red-600">{error}</p>}
          {data?.summary && <p className="whitespace-pre-wrap text-sm">{data.summary}</p>}
          {events.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              <p className="mb-1 inline-flex items-center gap-1 font-medium"><ShieldAlert className="h-3.5 w-3.5" /> Malpractice events</p>
              <ul className="space-y-0.5">
                {events.map((e, i) => (
                  <li key={i}>{[e.at ?? e.ts ?? e.timestamp, eventLabel(e)].filter(Boolean).join(" · ")}</li>
                ))}
              </ul>
            </div>
          )}
          {data && questions.length === 0 && <p className="text-sm text-muted-foreground">No question detail available.</p>}
          <ul className="space-y-3">
            {questions.map((q, i) => <Question key={q.id ?? i} q={q} index={i} />)}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}
