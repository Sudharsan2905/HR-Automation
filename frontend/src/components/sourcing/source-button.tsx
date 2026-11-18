"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { failRun, getRun, startRun } from "@/lib/api/sourcing";
import type { useSkillmateExtension } from "@/hooks/use-skillmate-extension";
import type { RunFailReason, SourcingJdDetail, SourcingRun } from "@/types/sourcing";
import { Loader2, Search, X } from "lucide-react";
import { toast } from "sonner";
import { ResdexLoginDialog } from "./resdex-login-dialog";

type Ext = ReturnType<typeof useSkillmateExtension>;

const ERROR_TEXT: Record<string, string> = {
  captcha: "Naukri is showing a CAPTCHA. Solve it in the ResDex tab, then try again.",
  skillmate_auth: "Your SkillMate session expired. Refresh this page and try again.",
  search_not_configured: "Open a Naukri ResDex results page first — automatic search isn't set up yet.",
  search_form_not_found: "Couldn't fill the ResDex search form — the page layout may have changed. Check the ResDex tab.",
  search_failed: "ResDex didn't run the search. Check the ResDex tab and try again.",
  extension_reloaded: "The SkillMate Sourcing extension was updated — reload this page to reconnect it.",
  no_results: "ResDex found no candidates for this JD's search. Try broader keywords in the search plan.",
};

const RELOAD_TEXT = "The SkillMate Sourcing extension was updated — reload this page to reconnect it.";

const KNOWN_FAIL: RunFailReason[] = ["not_logged_in", "captcha", "cancelled", "error"];

export function SourceButton({ jd, ext, onChanged }: { jd: SourcingJdDetail; ext: Ext; onChanged: () => void }) {
  const resumable = jd.active_run ? jd.active_run.id : null;
  const [busy, setBusy] = useState(!!resumable);
  const [runId, setRunId] = useState<string | null>(resumable);
  const [loginOpen, setLoginOpen] = useState(false);
  const handled = useRef<string | null>(null);
  const [run, setRun] = useState<SourcingRun | null>(null);
  const shownShortlisted = useRef(0);

  const progress = runId ? ext.progress[runId] : undefined;

  // Poll the run until it finishes
  useEffect(() => {
    if (!runId) return;
    const t = setInterval(async () => {
      try {
        const run = await getRun(runId);
        setRun(run);
        // Matches are shortlisted page by page: show each new one as it lands.
        if (run.profiles_shortlisted > shownShortlisted.current) {
          shownShortlisted.current = run.profiles_shortlisted;
          onChanged();
        }
        if (run.status === "done") {
          toast.success(run.profiles_shortlisted
            ? `Added ${run.profiles_shortlisted} new match${run.profiles_shortlisted > 1 ? "es" : ""}`
            : "No new matches this time");
        }
        if (run.status === "failed" && (run.error || "").startsWith("not_logged_in")) setLoginOpen(true);
        if (["done", "failed", "cancelled"].includes(run.status)) {
          shownShortlisted.current = 0;
          setRun(null);
          setRunId(null);
          setBusy(false);
          onChanged();
        }
      } catch { /* keep polling */ }
    }, 3000);
    return () => clearInterval(t);
  }, [runId, onChanged]);

  // React to extension errors: mark the run failed (the poll above then closes it out
  // and opens the login popup for not_logged_in).
  useEffect(() => {
    if (!runId || !progress || progress.stage !== "error" || handled.current === runId) return;
    handled.current = runId;
    const reason = progress.reason || "error";
    const failReason = KNOWN_FAIL.includes(reason as RunFailReason) ? (reason as RunFailReason) : "error";
    failRun(runId, failReason, failReason === reason ? "" : reason).catch(() => {});
    if (reason !== "not_logged_in") toast.error(ERROR_TEXT[reason] || `Sourcing stopped: ${reason}`);
  }, [runId, progress]);

  const click = async () => {
    setBusy(true);
    try {
      if (jd.pool_count === 0) {
        const login = await ext.checkLogin();
        if (login !== "ok") {
          if (login === "not_logged_in") setLoginOpen(true);
          else toast.error(login === "extension_reloaded" ? RELOAD_TEXT
            : "The SkillMate Sourcing extension didn't respond. Reload this page and try again.");
          setBusy(false);
          return;
        }
      }
      const res = await startRun(jd.id);
      if (res.mode === "pool" && res.run.status === "done") {
        toast.success(`Added ${res.run.profiles_shortlisted} from earlier results`);
        setBusy(false);
        onChanged();
        return;
      }
      if (res.mode === "pool") {   // earlier profiles not screened yet — SkillMate screens them now
        setRunId(res.run.id);
        onChanged();
        return;
      }
      ext.source({ runId: res.run.id, plan: res.search_plan!, pageFrom: res.page_from!, pageTo: res.page_to! });
      setRunId(res.run.id);
      onChanged();
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Could not start sourcing");
      setBusy(false);
    }
  };

  const cancel = () => {
    if (!runId) return;
    ext.cancel(runId);
    handled.current = runId;
    failRun(runId, "cancelled").catch(() => {}).finally(() => { setRunId(null); setBusy(false); onChanged(); });
  };

  const found = run?.profiles_shortlisted ?? 0;
  const tally = `${Math.min(found, 5)} of 5 found`;
  const stageText = run?.mode === "pool" ? `Screening earlier results… ${tally}`
    : run?.phase === "prefetch" ? "5 found — reading 2 more pages for next time…"
    : !progress ? "Starting…"
    : progress.stage === "searching" ? "Searching ResDex…"
    : progress.stage === "scraping" ? `Reading ResDex page ${progress.page ?? "…"}… ${tally}`
    : progress.stage === "screening" ? `Screening page ${progress.page ?? "…"}… ${tally}`
    : progress.stage === "done" ? "Finishing…"
    : "Stopping…";

  const disabled = ext.installed === false || ext.stale || jd.analysis_status !== "done" || busy;
  const button = (
    <Button onClick={click} disabled={disabled}>
      {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
      Source from Naukri (5)
    </Button>
  );

  return (
    <div className="flex items-center gap-2">
      {ext.installed === false || ext.stale ? (
        <Tooltip>
          <TooltipTrigger asChild><span>{button}</span></TooltipTrigger>
          <TooltipContent>
            {ext.stale ? RELOAD_TEXT : "Install the SkillMate Sourcing extension to source from Naukri"}
          </TooltipContent>
        </Tooltip>
      ) : button}
      {runId && (
        <>
          <span className="text-sm text-muted-foreground">{stageText}</span>
          <Button variant="ghost" size="sm" onClick={cancel}><X className="mr-1 h-3.5 w-3.5" /> Cancel</Button>
        </>
      )}
      <ResdexLoginDialog
        open={loginOpen}
        onCancel={() => setLoginOpen(false)}
        onRetry={() => { setLoginOpen(false); click(); }}
      />
    </div>
  );
}
