"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { failRun, getRun, startRun } from "@/lib/api/sourcing";
import type { useSkillmateExtension } from "@/hooks/use-skillmate-extension";
import { LINKEDIN_EXTENSION_MIN_VERSION, type useLinkedinExtension } from "@/hooks/use-linkedin-extension";
import type { RunFailReason, SourceKey, SourcingJdDetail, SourcingRun } from "@/types/sourcing";
import { Loader2, Search, X } from "lucide-react";
import { toast } from "sonner";
import { LinkedinLoginDialog } from "./linkedin-login-dialog";
import { ResdexLoginDialog } from "./resdex-login-dialog";

type Ext = ReturnType<typeof useSkillmateExtension>;
type LiExt = ReturnType<typeof useLinkedinExtension>;

const NAUKRI_ERRORS: Record<string, string> = {
  captcha: "Naukri is showing a CAPTCHA. Solve it in the ResDex tab, then try again.",
  skillmate_auth: "Your SkillMate session expired. Refresh this page and try again.",
  search_not_configured: "Open a Naukri ResDex results page first — automatic search isn't set up yet.",
  search_form_not_found: "Couldn't fill the ResDex search form — the page layout may have changed. Check the ResDex tab.",
  search_failed: "ResDex didn't run the search. Check the ResDex tab and try again.",
  extension_reloaded: "The SkillMate Sourcing extension was updated — reload this page to reconnect it.",
  no_results: "ResDex found no candidates for this JD's search. Try broader keywords in the search plan.",
};

const LINKEDIN_ERRORS: Record<string, string> = {
  captcha: "LinkedIn is asking for a security check. Complete it in the LinkedIn tab, then try again.",
  restricted: "LinkedIn limited this account (search limit or restriction). Try again later.",
  skillmate_auth: "Your SkillMate session expired. Refresh this page and try again.",
  search_failed: "LinkedIn didn't show search results. Check the LinkedIn tab and try again.",
  extension_reloaded: "The SkillMate LinkedIn extension was updated — reload this page to reconnect it.",
  no_results: "LinkedIn found none of your connections for this JD, even after SkillMate broadened the search step by step. Only 1st-degree connections can be taken (they are the ones who share an email). Check the keywords in the search plan, or re-analyze the JD.",
};

const RELOAD_TEXT = "A SkillMate sourcing extension was updated — reload this page to reconnect it.";
const INSTALL_TEXT = "Install the SkillMate Sourcing (Naukri) or SkillMate LinkedIn Sourcing extension to source candidates";

const KNOWN_FAIL: RunFailReason[] = ["not_logged_in", "captcha", "restricted", "cancelled", "error"];
const LABEL: Record<SourceKey, string> = { naukri: "ResDex", linkedin: "LinkedIn" };

function errorText(source: SourceKey, reason: string): string {
  const table = source === "linkedin" ? LINKEDIN_ERRORS : NAUKRI_ERRORS;
  return table[reason] || `Sourcing stopped: ${reason}`;
}

// A run's stored error ("captcha", "error: no_results", "search_form_not_found: …") in a few words.
function shortReason(error: string): string {
  const key = error.split(":")[0].trim();
  const detail = error.includes(":") ? error.split(":").slice(1).join(":").trim() : "";
  const map: Record<string, string> = {
    not_logged_in: "not logged in",
    captcha: "CAPTCHA",
    restricted: "account limited",
    search_form_not_found: "search form not found",
    search_failed: "search didn't run",
    no_results: "no results",
  };
  return map[key] || map[detail] || "error";
}

const ready = (e: { installed: boolean | null; stale: boolean }) => e.installed === true && !e.stale;
// LinkedIn also needs an up-to-date build: an old one keeps running after its files change until it is reloaded.
const liReady = (e: LiExt) => ready(e) && !e.outdated;
const outdatedText = (e: LiExt) =>
  `The LinkedIn extension is out of date (v${e.version}, needs ${LINKEDIN_EXTENSION_MIN_VERSION}). Open chrome://extensions and click Reload on "SkillMate LinkedIn Sourcing". This page notices by itself; if it still says out of date after a few seconds, reload the page.`;

export function SourceButton({ jd, ext, li, onChanged }: { jd: SourcingJdDetail; ext: Ext; li: LiExt; onChanged: () => void }) {
  const resumable = jd.active_run ? jd.active_run.id : null;
  const [busy, setBusy] = useState(!!resumable);
  const [runId, setRunId] = useState<string | null>(resumable);
  const [activeSource, setActiveSource] = useState<SourceKey>(jd.active_run?.source ?? "naukri");
  const [loginOpen, setLoginOpen] = useState<SourceKey | null>(null);
  const [run, setRun] = useState<SourcingRun | null>(null);
  const handled = useRef<string | null>(null);   // run whose extension error was already reported
  const closed = useRef<string | null>(null);    // run whose end was already processed
  const fellBack = useRef(false);                // this click already switched from Naukri to LinkedIn once
  const shownShortlisted = useRef(0);

  // The poll below outlives a render; give it the latest props.
  const latest = useRef({ jd, ext, li });
  useEffect(() => { latest.current = { jd, ext, li }; });

  const progress = runId ? (activeSource === "linkedin" ? li.progress[runId] : ext.progress[runId]) : undefined;

  // Start a run on `source` (or serve what is already waiting in SkillMate).
  const begin = async (source: SourceKey) => {
    const { jd: cur, ext: naukri, li: linkedin } = latest.current;
    const res = await startRun(cur.id, source);
    if (res.mode === "pool" && res.run.status === "done") {
      toast.success(`Added ${res.run.profiles_shortlisted} from earlier results`);
      setBusy(false);
      onChanged();
      return;
    }
    setActiveSource(source);
    if (res.mode === "pool") {   // earlier profiles not screened yet — SkillMate screens them now
      setRunId(res.run.id);
      onChanged();
      return;
    }
    const args = { runId: res.run.id, plan: res.search_plan!, pageFrom: res.page_from!, pageTo: res.page_to! };
    if (source === "linkedin") linkedin.source({ ...args, searchLevel: res.search_level ?? 0 });
    else naukri.source(args);
    setRunId(res.run.id);
    onChanged();
  };

  // Naukri first. LinkedIn when Naukri isn't installed, isn't logged in, has no more results, or doesn't respond.
  const pickSource = async (): Promise<SourceKey | null> => {
    const { jd: cur, ext: naukri, li: linkedin } = latest.current;
    let naukriLogin: string | null = null;
    let liLogin: string | null = null;
    if (ready(naukri) && !cur.pool_exhausted) {
      naukriLogin = await naukri.checkLogin();
      if (naukriLogin === "ok") return "naukri";
    }
    if (linkedin.outdated && ready(linkedin)) toast.warning(outdatedText(linkedin));
    if (liReady(linkedin) && !cur.linkedin_exhausted) {
      liLogin = await linkedin.checkLogin();
      if (liLogin === "ok") {
        if (naukriLogin) toast.info("Naukri isn't available right now — using LinkedIn.");
        return "linkedin";
      }
    }
    if (naukriLogin === "not_logged_in") { setLoginOpen("naukri"); return null; }
    if (liLogin === "not_logged_in") { setLoginOpen("linkedin"); return null; }
    if (naukriLogin === "extension_reloaded" || liLogin === "extension_reloaded") toast.error(RELOAD_TEXT);
    else if (naukriLogin || liLogin) toast.error("The sourcing extension didn't respond. Reload this page and try again.");
    else return ready(naukri) ? "naukri" : "linkedin";  // both exhausted: SkillMate serves leftovers or says so
    return null;
  };

  // A Naukri run that failed (CAPTCHA, form not found, no results, not logged in…): carry on with LinkedIn.
  const fallBackToLinkedin = async (failed: SourcingRun): Promise<boolean> => {
    const { jd: cur, li: linkedin } = latest.current;
    const error = failed.error || "";
    if (failed.source !== "naukri" || fellBack.current) return false;
    if (error.startsWith("cancelled") || error.includes("skillmate_auth")) return false;
    if (!liReady(linkedin) || cur.linkedin_exhausted) return false;
    fellBack.current = true;
    try {
      if ((await linkedin.checkLogin()) !== "ok") {
        toast.error("Naukri failed, and LinkedIn isn't logged in either.");
        return false;
      }
      toast.info(`Naukri stopped (${shortReason(error)}) — trying LinkedIn…`);
      await begin("linkedin");
      return true;
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Could not start LinkedIn sourcing");
      return false;
    }
  };

  // Poll the run until it finishes
  useEffect(() => {
    if (!runId) return;
    const t = setInterval(async () => {
      if (closed.current === runId) return;
      try {
        const current = await getRun(runId);
        if (closed.current === runId) return;
        setRun(current);
        // Matches are shortlisted page by page: show each new one as it lands.
        if (current.profiles_shortlisted > shownShortlisted.current) {
          shownShortlisted.current = current.profiles_shortlisted;
          onChanged();
        }
        if (current.status === "done") {
          if (current.profiles_shortlisted) {
            toast.success(`Added ${current.profiles_shortlisted} new match${current.profiles_shortlisted > 1 ? "es" : ""}`);
          } else if (current.source === "linkedin" && current.profiles_scanned > 0) {
            // LinkedIn candidates are taken only with an email: say why a run that read people added none.
            toast.info(`No new matches: ${current.profiles_scanned} LinkedIn connection${current.profiles_scanned > 1 ? "s were" : " was"} checked, ${current.profiles_received} shared an email and none passed the screening.`);
          } else {
            toast.success("No new matches this time");
          }
        }
        if (["done", "failed", "cancelled"].includes(current.status)) {
          closed.current = runId;
          shownShortlisted.current = 0;
          setRun(null);
          setRunId(null);
          onChanged();
          if (current.status === "failed" && await fallBackToLinkedin(current)) return;  // still busy: a new run started
          if (current.status === "failed" && (current.error || "").startsWith("not_logged_in")) setLoginOpen(current.source);
          setBusy(false);
        }
      } catch { /* keep polling */ }
    }, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, onChanged]);

  // React to extension errors: mark the run failed (the poll above then closes it out, falls back to
  // LinkedIn when it can, and opens the login popup for not_logged_in).
  useEffect(() => {
    if (!runId || !progress || progress.stage !== "error" || handled.current === runId) return;
    handled.current = runId;
    const reason = progress.reason || "error";
    const failReason = (KNOWN_FAIL as string[]).includes(reason) ? (reason as RunFailReason) : "error";
    failRun(runId, failReason, failReason === reason ? "" : reason).catch(() => {});
    if (reason !== "not_logged_in") toast.error(errorText(activeSource, reason));
  }, [runId, progress, activeSource]);

  const click = async () => {
    setBusy(true);
    fellBack.current = false;
    try {
      // Matches already waiting in SkillMate are served without opening any site.
      const source = jd.pool_count > 0 ? "naukri" : await pickSource();
      if (!source) { setBusy(false); return; }
      await begin(source);
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Could not start sourcing");
      setBusy(false);
    }
  };

  const cancel = () => {
    if (!runId) return;
    (activeSource === "linkedin" ? li : ext).cancel(runId);
    handled.current = runId;
    closed.current = runId;
    failRun(runId, "cancelled").catch(() => {}).finally(() => { setRunId(null); setBusy(false); onChanged(); });
  };

  const found = run?.profiles_shortlisted ?? 0;
  const tally = `${Math.min(found, 5)} of 5 found`;
  const site = LABEL[activeSource];
  const stageText = run?.mode === "pool" ? `Screening earlier results… ${tally}`
    : run?.phase === "prefetch" ? `5 found — reading ${activeSource === "linkedin" ? "an extra page" : "2 more pages"} for next time…`
    : !progress ? "Starting…"
    : progress.stage === "searching" ? `Searching ${site}…`
    : progress.stage === "contacts"
      ? `Checking contact details${progress.total ? ` ${progress.done ?? 0} of ${progress.total}` : ""} (page ${progress.page ?? "…"})… ${tally}`
    : progress.stage === "scraping" ? `Reading ${site} page ${progress.page ?? "…"}… ${tally}`
    : progress.stage === "screening" ? `Screening page ${progress.page ?? "…"}… ${tally}`
    : progress.stage === "done" ? "Finishing…"
    : "Stopping…";

  const noSource = !ready(ext) && !liReady(li);
  const disabled = noSource || jd.analysis_status !== "done" || busy;
  const button = (
    <Button onClick={click} disabled={disabled}>
      {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
      Source candidates (5)
    </Button>
  );
  const showTip = noSource && (ext.installed === false || li.installed === false || ext.stale || li.stale || li.outdated);

  return (
    <div className="flex items-center gap-2">
      {showTip ? (
        <Tooltip>
          <TooltipTrigger asChild><span>{button}</span></TooltipTrigger>
          <TooltipContent className="max-w-xs">
            {li.outdated && ready(li) ? outdatedText(li) : ext.stale || li.stale ? RELOAD_TEXT : INSTALL_TEXT}
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
        open={loginOpen === "naukri"}
        onCancel={() => setLoginOpen(null)}
        onRetry={() => { setLoginOpen(null); click(); }}
      />
      <LinkedinLoginDialog
        open={loginOpen === "linkedin"}
        onCancel={() => setLoginOpen(null)}
        onRetry={() => { setLoginOpen(null); click(); }}
      />
    </div>
  );
}
