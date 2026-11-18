"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { InterviewPagination } from "@/components/shared/interview-pagination";
import { EvaluationSummaryCard } from "@/components/interviewer/evaluation-summary-card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Percent, X } from "lucide-react";
import { getAllEvaluations } from "@/lib/api/evaluations";
import type { EvaluationListResponse } from "@/types/evaluation";
import { toast } from "sonner";

const PAGE_SIZE = 12;

export default function EvaluationsPage() {
  const [result, setResult] = useState<EvaluationListResponse | null>(null);
  const [fetching, setFetching] = useState(false);
  const [page, setPage] = useState(0);
  const [candidateInput, setCandidateInput] = useState("");
  const [percentageInput, setPercentageInput] = useState("");
  const [candidateSearch, setCandidateSearch] = useState<string | undefined>();
  const [maxPercentage, setMaxPercentage] = useState<number | undefined>();

  const candidateRef = useRef(candidateInput);
  candidateRef.current = candidateInput;
  const percentageRef = useRef(percentageInput);
  percentageRef.current = percentageInput;

  // Debounce candidate search
  useEffect(() => {
    const val = candidateInput.trim() || undefined;
    if (val === candidateSearch) return;
    const timer = setTimeout(() => {
      setCandidateSearch(val);
      setPage(0);
    }, 400);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateInput]);

  // Debounce percentage filter
  useEffect(() => {
    const raw = percentageInput.trim();
    const parsed = raw === "" ? undefined : parseFloat(raw);
    const val = parsed !== undefined && !isNaN(parsed) ? Math.min(100, Math.max(0, parsed)) : undefined;
    if (val === maxPercentage) return;
    const timer = setTimeout(() => {
      setMaxPercentage(val);
      setPage(0);
    }, 400);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [percentageInput]);

  const fetchPage = useCallback(async () => {
    setFetching(true);
    try {
      const data = await getAllEvaluations({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        candidate_search: candidateSearch,
        max_percentage: maxPercentage,
      });
      setResult(data);
    } catch {
      toast.error("Failed to load evaluations");
    } finally {
      setFetching(false);
    }
  }, [page, candidateSearch, maxPercentage]);

  useEffect(() => { fetchPage(); }, [fetchPage]);

  const hasFilters = !!candidateSearch || maxPercentage !== undefined;
  const clearAll = () => {
    setCandidateInput("");
    setPercentageInput("");
    setCandidateSearch(undefined);
    setMaxPercentage(undefined);
    setPage(0);
  };

  if (result === null) return <PageSkeleton />;

  return (
    <div className="flex flex-col flex-1 gap-4">
      <PageHeader title="Evaluations" description="Review interview results" />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400 pointer-events-none" />
          <Input
            className="pl-8 h-8 w-44 text-sm border-zinc-200 bg-white placeholder:text-zinc-400"
            placeholder="Search candidate..."
            value={candidateInput}
            onChange={(e) => setCandidateInput(e.target.value)}
          />
        </div>
        <div className="relative">
          <Percent className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400 pointer-events-none" />
          <Input
            type="number"
            min={0}
            max={100}
            className="pl-8 h-8 w-36 text-sm border-zinc-200 bg-white placeholder:text-zinc-400"
            placeholder="Max score %"
            value={percentageInput}
            onChange={(e) => setPercentageInput(e.target.value)}
          />
        </div>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs text-zinc-400 hover:text-zinc-700"
            onClick={clearAll}
          >
            <X className="h-3.5 w-3.5 mr-1" />
            Clear
          </Button>
        )}
      </div>

      <div className={fetching ? "flex-1 opacity-60 pointer-events-none transition-opacity" : "flex-1"}>
        {result.items.length === 0 ? (
          <EmptyState title="No evaluations found" description="Evaluations appear after interviews are completed" />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {result.items.map((e) => (
              <EvaluationSummaryCard key={e.id} evaluation={e} />
            ))}
          </div>
        )}
      </div>

      <InterviewPagination
        total={result.total}
        page={page}
        pageSize={PAGE_SIZE}
        onPageChange={setPage}
      />
    </div>
  );
}
