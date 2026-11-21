"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { listHiringFlows } from "@/lib/api/hiring";
import { Briefcase, Users, ClipboardCheck, Plus } from "lucide-react";
import { toast } from "sonner";
import type { HiringFlowSummary } from "@/types/hiring";

export default function DashboardPage() {
  const [flows, setFlows] = useState<HiringFlowSummary[] | null>(null);

  useEffect(() => {
    listHiringFlows()
      .then(setFlows)
      .catch(() => {
        toast.error("Failed to load dashboard");
        setFlows([]);
      });
  }, []);

  if (!flows) return <PageSkeleton />;

  const stats = [
    { label: "Open JDs", value: flows.length, icon: Briefcase },
    { label: "Candidates", value: flows.reduce((a, f) => a + f.candidate_count, 0), icon: Users },
    { label: "Level 1 done", value: flows.reduce((a, f) => a + f.stage_summary.level1_done, 0), icon: ClipboardCheck },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Your hiring overview"
        action={
          <Button asChild>
            <Link href="/hiring"><Plus className="mr-2 h-4 w-4" /> New JD</Link>
          </Button>
        }
      />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
        {stats.map((s) => (
          <Card key={s.label} className="rounded-xl border border-zinc-200 bg-gradient-to-br from-zinc-50/80 via-white to-slate-50 shadow-sm">
            <CardContent className="px-4 pt-4 pb-3">
              <div className="flex items-start justify-between mb-3">
                <p className="text-[13px] font-medium text-zinc-500 leading-tight">{s.label}</p>
                <s.icon className="h-4 w-4 text-zinc-400 shrink-0" />
              </div>
              <p className="text-2xl font-bold text-zinc-800">{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Recent hiring flows</h2>
        {flows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No JDs yet. Start one from the Hiring page.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {flows.slice(0, 6).map((f) => (
              <Link key={f.jd_id} href={`/hiring/${f.jd_id}`}>
                <Card className="h-full transition-colors hover:bg-muted/40">
                  <CardContent className="space-y-1 p-4">
                    <p className="truncate font-semibold">{f.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {f.candidate_count} candidates · L1 done {f.stage_summary.level1_done}
                    </p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
