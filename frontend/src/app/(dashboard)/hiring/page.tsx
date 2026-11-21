"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NewJdDialog } from "@/components/hiring/new-jd-dialog";
import { listHiringFlows } from "@/lib/api/hiring";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import type { HiringFlowSummary } from "@/types/hiring";

const STAGE_LABEL: Record<string, string> = {
  jd: "JD analysis",
  sourcing: "Sourcing",
  level1: "Level 1",
  report: "Report",
  done: "Completed",
};

export default function HiringPage() {
  const [items, setItems] = useState<HiringFlowSummary[] | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      listHiringFlows()
        .then((rows) => { if (!cancelled) setItems(rows); })
        .catch(() => {
          if (cancelled) return;
          toast.error("Failed to load hiring flows");
          setItems((prev) => prev ?? []);
        });
    load();
    const t = setInterval(load, 10000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (items === null) return <PageSkeleton />;

  const newButton = (
    <Button onClick={() => setOpen(true)}>
      <Plus className="mr-2 h-4 w-4" /> New JD
    </Button>
  );

  return (
    <div className="flex flex-1 flex-col gap-4">
      <PageHeader
        title="Hiring"
        description="From job description to final report, in one place"
        action={newButton}
      />

      {items.length === 0 ? (
        <EmptyState title="No hiring flows yet" description="Add a job description to start sourcing and screening." action={newButton} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((f) => (
            <Link key={f.jd_id} href={`/hiring/${f.jd_id}`}>
              <Card className="h-full transition-colors hover:bg-muted/40">
                <CardContent className="space-y-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <p className="truncate font-semibold">{f.title}</p>
                    <Badge variant="secondary">{STAGE_LABEL[f.current_stage] || f.current_stage}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>Candidates <b className="text-foreground">{f.candidate_count}</b></span>
                    <span>Level 1 done <b className="text-foreground">{f.stage_summary.level1_done}</b></span>
                  </div>
                  <p className="text-[11px] text-muted-foreground">{new Date(f.created_at).toLocaleString()}</p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}

      <NewJdDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
