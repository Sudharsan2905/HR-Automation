"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { saveContact, setProfileStatus } from "@/lib/api/sourcing";
import type { useSkillmateExtension } from "@/hooks/use-skillmate-extension";
import type { useLinkedinExtension } from "@/hooks/use-linkedin-extension";
import type { ProfileStatus, SourcedProfile, SourcingRun, StatusCounts } from "@/types/sourcing";
import { ExternalLink, Eye, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { LinkedinLoginDialog } from "./linkedin-login-dialog";
import { ProfileDetailSheet } from "./profile-detail-sheet";
import { ResdexLoginDialog } from "./resdex-login-dialog";

type Ext = ReturnType<typeof useSkillmateExtension>;
type LiExt = ReturnType<typeof useLinkedinExtension>;

const isLinkedin = (p: { source: string }) => p.source === "LinkedIn";
type Tab = "shortlisted" | "selected" | "on_hold" | "rejected" | "all";

const TABS: { value: Tab; label: string }[] = [
  { value: "shortlisted", label: "Shortlisted" },
  { value: "selected", label: "Selected" },
  { value: "on_hold", label: "On hold" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

const BREAKDOWN_LABELS: Record<string, string> = {
  base: "Base", related_penalty: "Similar-skill penalty", strength_bonus: "Skill strength", preferred_bonus: "Preferred skills",
  target_company: "Target company", projects: "Projects", location: "Location", seniority: "Seniority",
};

function ScoreCell({ p }: { p: SourcedProfile }) {
  if (p.score == null) return <span className="text-muted-foreground">—</span>;
  const b = p.score_breakdown || {};
  return (
    <Tooltip>
      <TooltipTrigger asChild><span className="cursor-help font-semibold">{p.score}</span></TooltipTrigger>
      <TooltipContent className="space-y-0.5 text-xs">
        {b.rejected_reason ? <p>Rejected: {String(b.rejected_reason)}</p> : Object.entries(BREAKDOWN_LABELS)
          .filter(([k]) => typeof b[k] === "number" && b[k] !== 0)
          .map(([k, label]) => <p key={k}>{label}: {Number(b[k]) > 0 ? "+" : ""}{String(b[k])}</p>)}
      </TooltipContent>
    </Tooltip>
  );
}

export function ProfilesTable({ profiles, counts, runs, ext, li, onChanged }: {
  profiles: SourcedProfile[];
  counts: StatusCounts;
  runs: SourcingRun[];
  ext: Ext;
  li: LiExt;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("shortlisted");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [emailFor, setEmailFor] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [viewId, setViewId] = useState<string | null>(null);
  const viewing = viewId ? profiles.find((p) => p.id === viewId) ?? null : null;
  const [loginFor, setLoginFor] = useState<SourcedProfile | null>(null);

  const runNo = (id: string | null) => runs.find((r) => r.id === id)?.run_no;
  const rows = tab === "all" ? profiles : profiles.filter((p) => p.status === tab);
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  const reportCandidate = (res: { candidate_error: string | null; profile: SourcedProfile }) => {
    if (res.candidate_error) toast.error(res.candidate_error);
    else if (res.profile.candidate_user_id) toast.success(`${res.profile.name} added to Candidates`);
  };

  // LinkedIn shows a phone/email only for people the recruiter is connected to, so "no email" is an ordinary
  // outcome there: say so and let the recruiter type it in.
  const linkedinReveal = async (p: SourcedProfile) => {
    if (!li.installed || li.stale) {
      toast.error(li.stale
        ? "The SkillMate LinkedIn extension was updated — reload this page to reconnect it."
        : "Install the SkillMate LinkedIn extension to read contact details — or enter the email manually.");
      setEmailFor(p.id);
      return;
    }
    const login = await li.checkLogin();
    if (login === "not_logged_in") {
      setLoginFor(p);
      return;
    }
    if (login !== "ok") {
      toast.error("The SkillMate LinkedIn extension didn't respond. Reload this page and try again.");
      setEmailFor(p.id);
      return;
    }
    const res = await li.reveal({ profileId: p.id, name: p.name, sourceLink: p.source_link });
    if (res.ok && res.candidateError) {
      onChanged();
      toast.error(res.candidateError);
      setEmailFor(p.id);
    } else if (res.ok) {
      onChanged();
      toast.success(`Contact details saved for ${p.name}`);
    } else if (res.reason === "not_logged_in") {
      setLoginFor(p);
    } else {
      toast.error(
        res.reason === "no_email" ? `${p.name} hasn't shared an email with you on LinkedIn — enter it manually.`
        : res.reason === "busy" ? "A LinkedIn search is running — enter the email manually, or try again when it finishes."
        : res.reason === "captcha" ? "LinkedIn is asking for a security check — complete it in the LinkedIn tab, then try again."
        : res.reason === "restricted" ? "LinkedIn limited this account for now — enter the email manually."
        : "Couldn't read an email from the LinkedIn profile — enter it manually.");
      setEmailFor(p.id);
    }
  };

  const revealAndSave = async (p: SourcedProfile) => {
    if (isLinkedin(p)) return linkedinReveal(p);
    const login = await ext.checkLogin();
    if (login === "not_logged_in") {
      setLoginFor(p);
      return;
    }
    if (login !== "ok") {
      toast.error(login === "extension_reloaded"
        ? "The SkillMate Sourcing extension was updated — reload this page to reconnect it."
        : "The SkillMate Sourcing extension didn't respond. Reload this page and try again.");
      return;
    }
    const res = await ext.reveal({ profileId: p.id, name: p.name, sourceLink: p.source_link });
    if (res.ok && res.candidateError) {
      onChanged();
      toast.error(res.candidateError);
      setEmailFor(p.id);
    } else if (res.ok) {
      onChanged();
      toast.success(`Contact details saved for ${p.name}`);
    } else if (res.reason === "not_logged_in") {
      setLoginFor(p);
    } else {
      toast.error("Couldn't read an email from the profile — enter it manually.");
      setEmailFor(p.id);
    }
  };

  const act = async (p: SourcedProfile, status: "selected" | "rejected" | "on_hold") => {
    let note = "";
    if (status === "rejected") {
      const n = window.prompt(`Reason for rejecting ${p.name} (optional)`);
      if (n === null) return;
      note = n;
    }
    setBusyId(p.id);
    try {
      const res = await setProfileStatus(p.id, status, note);
      onChanged();
      if (status === "selected") {
        if (res.needs_contact) await revealAndSave(res.profile);
        else if (res.candidate_error) { toast.error(res.candidate_error); setEmailFor(p.id); }
        else if (res.profile.candidate_user_id) toast.success(`${p.name} added to Candidates`);
      }
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Update failed");
    } finally {
      setBusyId(null);
    }
  };

  const submitEmail = async (p: SourcedProfile) => {
    setBusyId(p.id);
    try {
      reportCandidate(await saveContact(p.id, { email: email.trim() }));
      setEmailFor(null);
      setEmail("");
      onChanged();
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Could not save the email");
    } finally {
      setBusyId(null);
    }
  };

  // Select / Hold / Reject — shared by the table rows and the profile panel.
  const actions = (p: SourcedProfile) => {
    if (p.status === "below_threshold") return null;  // under the score threshold: view only
    if (busyId === p.id) return <Loader2 className="h-4 w-4 animate-spin" />;
    return (
      <>
        {p.status !== "selected" && <Button size="sm" variant="outline" onClick={() => act(p, "selected")}>Select</Button>}
        {p.status === "selected" && !p.candidate_user_id && emailFor !== p.id && (
          p.email
            ? <Button size="sm" variant="outline" onClick={() => setEmailFor(p.id)}>Use a different email</Button>
            : <Button size="sm" variant="outline" onClick={() => revealAndSave(p)}>Get contact</Button>
        )}
        {p.status !== "on_hold" && <Button size="sm" variant="ghost" onClick={() => act(p, "on_hold")}>Hold</Button>}
        {p.status !== "rejected" && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => act(p, "rejected")}>Reject</Button>}
      </>
    );
  };

  return (
    <div className="space-y-3">
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} className="text-xs">
              {t.label} ({t.value === "all" ? total : counts[t.value as ProfileStatus] ?? 0})
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          {tab === "shortlisted"
            ? (total > 0
              ? `No shortlisted profiles yet. ${total} found profile${total > 1 ? "s are" : " is"} under “All” — click “Source candidates” to screen them and shortlist 5.`
              : "No shortlisted profiles yet. Click “Source candidates” to find 5.")
            : "Nothing here."}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Current role</TableHead>
              <TableHead>Exp</TableHead>
              <TableHead>CTC</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Score</TableHead>
              <TableHead className="min-w-[240px]">Why</TableHead>
              <TableHead>Run</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">
                  <button type="button" onClick={() => setViewId(p.id)} title="View full profile"
                    className="text-left text-primary underline decoration-dotted underline-offset-4 hover:decoration-solid">
                    {p.name}
                  </button>
                  <a href={p.source_link} target="_blank" rel="noopener noreferrer"
                    title={`Open in ${isLinkedin(p) ? "LinkedIn" : "ResDex"}`}
                    className="ml-1 inline-flex text-muted-foreground hover:text-foreground">
                    <ExternalLink className="h-3 w-3" />
                  </a>
                  <Badge variant="secondary" className="ml-2 text-[10px]">{p.source || "Naukri"}</Badge>
                  {p.status !== tab && <Badge variant="outline" className="ml-2 text-[10px] capitalize">{p.status.replace("_", " ")}</Badge>}
                </TableCell>
                <TableCell className="text-sm">{[p.current_title, p.current_company].filter(Boolean).join(" @ ") || p.headline || "—"}</TableCell>
                <TableCell>{p.experience_years != null ? `${p.experience_years} y` : "—"}</TableCell>
                <TableCell>{p.current_ctc_lacs != null ? `${p.current_ctc_lacs} L` : "—"}</TableCell>
                <TableCell className="text-sm">{p.location || "—"}</TableCell>
                <TableCell><ScoreCell p={p} /></TableCell>
                <TableCell className="text-xs">
                  {p.match_reasons.map((r, i) => <p key={i}>{r}</p>)}
                  {p.related_notes.map((r, i) => <p key={`rel-${i}`} className="text-amber-600">{r}</p>)}
                  {p.status === "selected" && p.candidate_user_id && (
                    <p className="mt-1 text-emerald-600">
                      {p.existing_candidate_owner ? `Already a SkillMate candidate (added by ${p.existing_candidate_owner})` : "Candidate created"}
                    </p>
                  )}
                  {emailFor === p.id && (
                    <div className="mt-2 flex gap-1">
                      <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Candidate email" className="h-7 text-xs" />
                      <Button size="sm" className="h-7" disabled={!email.trim() || busyId === p.id} onClick={() => submitEmail(p)}>Save</Button>
                    </div>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">#{runNo(p.shortlisted_in_run_id ?? p.run_id) ?? "—"}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setViewId(p.id)}><Eye className="mr-1 h-3.5 w-3.5" /> View</Button>
                    {actions(p)}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <ProfileDetailSheet profile={viewing} onClose={() => setViewId(null)} actions={actions} />

      <ResdexLoginDialog
        open={!!loginFor && !isLinkedin(loginFor)}
        onCancel={() => setLoginFor(null)}
        onRetry={() => { const p = loginFor; setLoginFor(null); if (p) revealAndSave(p); }}
      />
      <LinkedinLoginDialog
        open={!!loginFor && isLinkedin(loginFor)}
        onCancel={() => setLoginFor(null)}
        onRetry={() => { const p = loginFor; setLoginFor(null); if (p) revealAndSave(p); }}
      />
    </div>
  );
}
