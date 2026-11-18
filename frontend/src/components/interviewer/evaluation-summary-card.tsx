"use client";

import Link from "next/link";
import { formatDate } from "@/lib/utils";
import type { EvaluationSummary } from "@/types/evaluation";

function _percentageColor(pct: number): string {
  if (pct >= 85) return "text-green-600";
  if (pct >= 70) return "text-blue-600";
  if (pct >= 55) return "text-yellow-600";
  if (pct >= 40) return "text-orange-600";
  return "text-red-600";
}

export function EvaluationSummaryCard({ evaluation }: { evaluation: EvaluationSummary }) {
  const color = _percentageColor(evaluation.percentage);

  return (
    <Link href={`/evaluations/${evaluation.interview_id}`}>
      <div className="rounded-xl border border-zinc-900 bg-gradient-to-br from-zinc-50 via-white to-slate-100 hover:from-slate-100 hover:via-zinc-50 hover:to-white hover:shadow-lg hover:shadow-zinc-200/60 hover:-translate-y-0.5 transition-all duration-300 cursor-pointer h-full">
        <div className="px-4 py-3 space-y-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-zinc-800">{evaluation.candidate_name}</span>
              {evaluation.is_partial && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full border border-amber-400 text-amber-600 bg-amber-50 leading-none">
                  Partial
                </span>
              )}
            </div>
            {evaluation.candidate_mail && (
              <p className="text-xs text-zinc-500 truncate">{evaluation.candidate_mail}</p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <div className="relative h-12 w-12 shrink-0">
              <svg className="h-12 w-12 -rotate-90" viewBox="0 0 36 36">
                <path
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  className="text-zinc-200"
                />
                <path
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeDasharray={`${evaluation.percentage}, 100`}
                  className={color}
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[11px] font-bold text-zinc-800">
                {Math.round(evaluation.percentage)}%
              </span>
            </div>
            <div className="text-xs text-zinc-500">
              <p>{evaluation.total_score}/{evaluation.max_score} pts</p>
              <p>{formatDate(evaluation.evaluated_at)}</p>
            </div>
          </div>
        </div>
      </div>
    </Link>
  );
}
