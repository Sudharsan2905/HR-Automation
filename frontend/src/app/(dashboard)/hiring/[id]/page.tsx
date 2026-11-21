"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { StatusBadge } from "@/components/shared/status-dot";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RequirementsCard } from "@/components/sourcing/requirements-card";
import { SearchPlanCard } from "@/components/sourcing/search-plan-card";
import { SourceButton } from "@/components/sourcing/source-button";
import { ProfilesTable } from "@/components/sourcing/profiles-table";
import { StageStepper } from "@/components/hiring/stage-stepper";
import { ActivityFeed, Level1RunPanel } from "@/components/hiring/level1-run-panel";
import { CandidatesTable } from "@/components/hiring/candidates-table";
import { Level1DetailSheet } from "@/components/hiring/level1-detail-sheet";
import { useSkillmateExtension } from "@/hooks/use-skillmate-extension";
import { useLinkedinExtension } from "@/hooks/use-linkedin-extension";
import {
  deleteSourcingJd, getSourcingJd, listProfiles, reanalyzeSourcingJd, updateRequirements, updateSearchPlan,
} from "@/lib/api/sourcing";
import { getHiringFlow, startLevel1 } from "@/lib/api/hiring";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { SourcedProfile, SourcingJdDetail } from "@/types/sourcing";
import type { FlowCandidate, HiringFlow } from "@/types/hiring";

const FAST_MS = 2000;
const SLOW_MS = 8000;

function isActive(f: HiringFlow) {
  return (
    f.jd.analysis_status === "generating" ||
    f.stages.some((s) => s.status === "running") ||
    f.level1_run?.status === "running" ||
    f.candidates.some((c) => ["in_progress", "evaluating"].includes(c.level1.status))
  );
}

export default function HiringFlowPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const ext = useSkillmateExtension();
  const li = useLinkedinExtension();

  const [jd, setJd] = useState<SourcingJdDetail | null>(null);
  const [profiles, setProfiles] = useState<SourcedProfile[]>([]);
  const [flow, setFlow] = useState<HiringFlow | null>(null);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [viewL1, setViewL1] = useState<FlowCandidate | null>(null);

  const [tick, setTick] = useState(0);
  const load = useCallback(() => setTick((n) => n + 1), []);
  const [flowTick, setFlowTick] = useState(0);
  const reloadFlow = useCallback(() => setFlowTick((n) => n + 1), []);

  // Sourcing JD + profiles
  useEffect(() => {
    let cancelled = false;
    Promise.all([getSourcingJd(id), listProfiles(id)])
      .then(([detail, rows]) => {
        if (cancelled) return;
        setJd(detail);
        setProfiles(rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        toast.error((err as { message?: string })?.message || "Failed to load");
        router.replace("/hiring");
      });
    return () => { cancelled = true; };
  }, [id, router, tick]);

  const working = jd?.analysis_status === "generating" || !!jd?.active_run;
  useEffect(() => {
    if (!working) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [working, load]);

  // Flow: every 2s while anything is active, otherwise every 8s
  const activeRef = useRef(true);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      try {
        const f = await getHiringFlow(id);
        if (cancelled) return;
        setFlow(f);
        setFlowError(null);
        activeRef.current = isActive(f);
      } catch (err: unknown) {
        if (cancelled) return;
        setFlowError((err as { message?: string })?.message || "Could not load the hiring flow");
      }
      if (!cancelled) timer = setTimeout(run, activeRef.current ? FAST_MS : SLOW_MS);
    };
    run();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [id, flowTick]);

  // Keep sourcing data fresh while the flow is sourcing
  const sourcingRunning = flow?.stages.some((s) => s.key === "sourcing" && s.status === "running");
  useEffect(() => {
    if (!sourcingRunning || working) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [sourcingRunning, working, load]);

  if (!jd) return <PageSkeleton />;

  const onDelete = async () => {
    if (!window.confirm("Delete this JD and all its sourced profiles?")) return;
    try {
      await deleteSourcingJd(jd.id);
      router.replace("/hiring");
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Delete failed");
    }
  };

  const onStartLevel1 = async () => {
    setStarting(true);
    try {
      await startLevel1(jd.id);
      toast.success("Level 1 started");
      reloadFlow();
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Could not start Level 1");
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="flex flex-1 flex-col gap-4">
      <PageHeader
        title={jd.requirements.role_title || jd.title}
        description={jd.title !== jd.requirements.role_title ? jd.title : undefined}
        backHref="/hiring"
        action={
          <div className="flex items-center gap-2">
            {jd.analysis_status === "done" && <SourceButton jd={jd} ext={ext} li={li} onChanged={() => { load(); reloadFlow(); }} />}
            <Button variant="ghost" size="icon" title="Delete" onClick={onDelete}><Trash2 className="h-4 w-4" /></Button>
          </div>
        }
      />

      {flow ? <StageStepper stages={flow.stages} /> : flowError ? (
        <p className="whitespace-pre-wrap rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{flowError}</p>
      ) : null}

      {jd.analysis_status !== "done" ? (
        <Card>
          <CardContent className="flex items-center justify-between gap-4 p-5">
            {jd.analysis_status === "generating" ? (
              <p className="inline-flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" /> Analyzing the JD and building the candidate search…</p>
            ) : (
              <>
                <div className="space-y-1">
                  <StatusBadge status="failed" label="analysis failed" />
                  <p className="whitespace-pre-wrap text-sm text-muted-foreground">{jd.analysis_error}</p>
                </div>
                <Button variant="outline" onClick={async () => { await reanalyzeSourcingJd(jd.id); load(); reloadFlow(); }}>
                  <RefreshCw className="mr-2 h-4 w-4" /> Re-analyze
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="pipeline">
          <TabsList>
            <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
            <TabsTrigger value="sourcing">JD &amp; Sourcing</TabsTrigger>
          </TabsList>

          <TabsContent value="pipeline" className="mt-4 space-y-4">
            {flow ? (
              <>
                <div className="grid gap-4 lg:grid-cols-2">
                  <Level1RunPanel flow={flow} starting={starting} onStart={onStartLevel1} />
                  <ActivityFeed flow={flow} />
                </div>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">
                      Candidates
                      <span className="ml-2 text-sm font-normal text-muted-foreground">
                        Level 1 pass mark above {flow.settings.pass_percent}%
                      </span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <CandidatesTable
                      candidates={flow.candidates}
                      passPercent={flow.settings.pass_percent}
                      onViewLevel1={setViewL1}
                      onChanged={reloadFlow}
                    />
                  </CardContent>
                </Card>
              </>
            ) : !flowError ? (
              <PageSkeleton />
            ) : null}
          </TabsContent>

          <TabsContent value="sourcing" className="mt-4 space-y-4">
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                disabled={!!jd.active_run}
                title={jd.active_run ? "Wait for the running sourcing run to finish" : undefined}
                onClick={async () => {
                  if (!window.confirm("Rebuild the requirements and the candidate search from the JD text? Your edits to them will be replaced.")) return;
                  try {
                    await reanalyzeSourcingJd(jd.id);
                    toast.info("Re-analyzing the JD…");
                    load();
                    reloadFlow();
                  } catch (err: unknown) {
                    toast.error((err as { message?: string })?.message || "Could not re-analyze");
                  }
                }}
              >
                <RefreshCw className="mr-2 h-4 w-4" /> Re-analyze JD
              </Button>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <RequirementsCard
                requirements={jd.requirements}
                onSave={async (req) => { setJd(await updateRequirements(jd.id, req)); toast.success("Requirements saved"); load(); }}
              />
              <SearchPlanCard
                plan={jd.search_plan}
                onSave={async (plan) => { setJd(await updateSearchPlan(jd.id, plan)); toast.success("Search updated"); }}
              />
            </div>
            {jd.pool_count === 0 && jd.pool_exhausted && (jd.linkedin_exhausted || li.installed === false) && (
              <p className="text-sm text-amber-600">No more matches for this search. Edit the keywords or switch between primary and narrowed.</p>
            )}
            <Card>
              <CardContent className="p-4">
                <ProfilesTable profiles={profiles} counts={jd.counts} runs={jd.runs} ext={ext} li={li} onChanged={() => { load(); reloadFlow(); }} />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}

      <Level1DetailSheet
        candidate={viewL1}
        fallbackAssessmentId={flow?.level1_run?.assessment_id}
        onClose={() => setViewL1(null)}
      />
    </div>
  );
}
