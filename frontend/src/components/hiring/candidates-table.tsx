"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { promoteCandidate, resendLevel1, resendLevel2Key } from "@/lib/api/hiring";
import { cn, formatDate } from "@/lib/utils";
import { CheckCircle2, Loader2, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import type { FlowCandidate, Level1Status, Level2Status } from "@/types/hiring";

const L1_BADGE: Record<Level1Status, string> = {
  not_started: "bg-zinc-100 text-zinc-700",
  invited: "bg-amber-100 text-amber-800",
  in_progress: "bg-sky-100 text-sky-800",
  evaluating: "bg-blue-100 text-blue-800",
  passed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  terminated: "bg-red-100 text-red-800",
};

const L2_BADGE: Record<Level2Status, string> = {
  not_started: "bg-zinc-100 text-zinc-700",
  scheduled: "bg-amber-100 text-amber-800",
  in_progress: "bg-sky-100 text-sky-800",
  completed: "bg-blue-100 text-blue-800",
  report_ready: "bg-emerald-100 text-emerald-800",
};

const label = (s: string) => s.replace(/_/g, " ");

export function CandidatesTable({ candidates, passPercent, onViewLevel1, onChanged }: {
  candidates: FlowCandidate[];
  passPercent: number;
  onViewLevel1: (c: FlowCandidate) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<{ sent?: boolean; interview_id?: string }>, ok: string) => {
    setBusy(key);
    try {
      const res = await fn();
      if (res.sent === false) toast.error("The email could not be sent. Check the activity log.");
      else toast.success(ok);
      onChanged();
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Action failed");
    } finally {
      setBusy(null);
    }
  };

  if (candidates.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">No candidates in this flow yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Candidate</TableHead>
          <TableHead>Sourcing score</TableHead>
          <TableHead>Level 1 (pass above {passPercent}%)</TableHead>
          <TableHead>Level 2</TableHead>
          <TableHead>Final report</TableHead>
          <TableHead className="w-10" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {candidates.map((c) => {
          const l1 = c.level1;
          const l2 = c.level2;
          const pct = l1.percentage;
          const pctColor = l1.status === "passed" ? "text-emerald-600" : l1.status === "failed" || l1.status === "terminated" ? "text-red-600" : "";
          const canViewL1 = !!l1.submission_id;
          const hasEval = !!l2.interview_id && (l2.status === "completed" || l2.status === "report_ready");
          const live = !!l2.interview_id && l2.status === "in_progress";
          const rowBusy = busy?.startsWith(c.id) ?? false;
          return (
            <TableRow key={c.id}>
              <TableCell>
                <p className="font-medium">{c.name}</p>
                <p className="text-xs text-muted-foreground">{c.email || "no email"}</p>
              </TableCell>
              <TableCell>{c.score != null ? c.score : "—"}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className={L1_BADGE[l1.status]}>{label(l1.status)}</Badge>
                  {pct != null && <span className={cn("text-sm font-semibold tabular-nums", pctColor)}>{Math.round(pct * 10) / 10}%</span>}
                </div>
                {l1.status === "invited" && l1.key_expires_at && (
                  <p className="mt-0.5 text-[11px] text-muted-foreground">Key expires {formatDate(l1.key_expires_at)}</p>
                )}
              </TableCell>
              <TableCell>
                <Badge variant="secondary" className={L2_BADGE[l2.status]}>{label(l2.status)}</Badge>
                {l2.due_date && l2.status === "scheduled" && (
                  <p className="mt-0.5 text-[11px] text-muted-foreground">Due {formatDate(l2.due_date)}</p>
                )}
                {l2.recommendation && <p className="mt-0.5 text-xs">{l2.recommendation}</p>}
              </TableCell>
              <TableCell>
                {c.final_report_sent
                  ? <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> Sent</span>
                  : <span className="text-xs text-muted-foreground">Pending</span>}
              </TableCell>
              <TableCell>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8" disabled={rowBusy}>
                      {rowBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MoreHorizontal className="h-4 w-4" />}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem disabled={!canViewL1} onClick={() => onViewLevel1(c)}>View Level 1 detail</DropdownMenuItem>
                    {hasEval && (
                      <DropdownMenuItem asChild><Link href={`/evaluations/${l2.interview_id}`}>View Level 2 evaluation</Link></DropdownMenuItem>
                    )}
                    {live && (
                      <DropdownMenuItem asChild><Link href={`/interviews/${l2.interview_id}/live`}>Watch Level 2 live</Link></DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      disabled={!c.email || !["not_started", "invited"].includes(l1.status)}
                      onClick={() => run(`${c.id}:l1`, () => resendLevel1(c.id), "Level 1 invite re-sent")}
                    >
                      Resend Level 1 key
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={l2.status !== "scheduled"}
                      onClick={() => run(`${c.id}:l2`, () => resendLevel2Key(c.id), "Level 2 key re-sent")}
                    >
                      Resend Level 2 key
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={l2.status !== "not_started"}
                      onClick={() => {
                        if (!window.confirm(`Promote ${c.name} to Level 2 regardless of the Level 1 result?`)) return;
                        run(`${c.id}:promote`, () => promoteCandidate(c.id), "Scheduled for Level 2");
                      }}
                    >
                      Promote to Level 2
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
