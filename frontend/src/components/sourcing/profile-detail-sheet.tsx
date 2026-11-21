"use client";

import { type ReactNode, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { getProfile } from "@/lib/api/sourcing";
import type { SourcedProfile, SourcedProfileDetail } from "@/types/sourcing";
import { Check, ExternalLink, Mail, Minus, Phone, X } from "lucide-react";

const STATUS_STYLE: Record<string, string> = {
  shortlisted: "bg-cyan-100 text-cyan-800",
  selected: "bg-green-100 text-green-800",
  on_hold: "bg-amber-100 text-amber-800",
  rejected: "bg-red-100 text-red-800",
  pool: "bg-muted text-muted-foreground",
  below_threshold: "bg-muted text-muted-foreground",
};

const BREAKDOWN_LABELS: Record<string, string> = {
  base: "Base", related_penalty: "Similar-skill penalty", strength_bonus: "Skill strength", preferred_bonus: "Preferred skills",
  target_company: "Target company", projects: "Projects", location: "Location", seniority: "Seniority",
};

const label = (s: string) => s.replace(/_/g, " ");

// Scraped rows have no fixed shape: show the known fields, fall back to any text values.
function pick(row: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "string" && v.trim()) return v.trim();
    if (typeof v === "number") return String(v);
  }
  return "";
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export function ProfileDetailSheet({ profile, onClose, actions }: {
  /** The row the recruiter opened (from the list) — its status/contact changes trigger a refresh. */
  profile: SourcedProfile | null;
  onClose: () => void;
  /** Same Select / Hold / Reject buttons the table uses. */
  actions: (p: SourcedProfile) => ReactNode;
}) {
  const [detail, setDetail] = useState<SourcedProfileDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = profile?.id;
  const version = profile ? `${profile.status}|${profile.candidate_user_id}|${profile.email}|${profile.phone}` : "";

  useEffect(() => {
    if (!id) return;
    let live = true;
    getProfile(id)
      .then((d) => { if (live) { setDetail(d); setError(null); } })
      .catch((e: { message?: string }) => { if (live) setError(e?.message || "Could not load this profile"); });
    return () => { live = false; };
  }, [id, version]);

  const d = detail && detail.id === id ? detail : null;
  const b = d?.score_breakdown || {};

  return (
    <Sheet open={!!profile} onOpenChange={(open) => { if (!open) { onClose(); setDetail(null); } }}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="border-b p-5">
          <div className="flex items-start justify-between gap-3 pr-6">
            <div className="min-w-0">
              <SheetTitle className="truncate text-lg">{profile?.name}</SheetTitle>
              <SheetDescription className="text-sm">
                {[profile?.current_title, profile?.current_company].filter(Boolean).join(" @ ") || profile?.headline || "—"}
              </SheetDescription>
            </div>
            {profile && (
              <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLE[profile.status] || ""}`}>
                {label(profile.status)}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>{d?.total_experience || (profile?.experience_years != null ? `${profile.experience_years} y` : "Exp —")}</span>
            <span>{d?.current_ctc || (profile?.current_ctc_lacs != null ? `${profile.current_ctc_lacs} L` : "CTC —")}</span>
            <span>{profile?.location || "Location —"}</span>
          </div>
          {profile && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {actions(profile)}
              <a href={profile.source_link} target="_blank" rel="noopener noreferrer"
                className="ml-auto inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground hover:underline">
                Open in {profile.source === "LinkedIn" ? "LinkedIn" : "ResDex"} <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </div>
          )}
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-190px)]">
          <div className="space-y-6 p-5">
            {error && <p className="text-sm text-destructive">{error}</p>}
            {!d && !error && <div className="space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>}

            {d && (
              <>
                {(d.email || d.phone) && (
                  <Section title="Contact">
                    <div className="space-y-1 text-sm">
                      {d.email && <p className="flex items-center gap-2"><Mail className="h-3.5 w-3.5" /> {d.email}</p>}
                      {d.phone && <p className="flex items-center gap-2"><Phone className="h-3.5 w-3.5" /> {d.phone}</p>}
                    </div>
                  </Section>
                )}

                <Section title="Score">
                  {d.score == null ? <p className="text-sm text-muted-foreground">Not screened yet.</p> : (
                    <div className="flex items-start gap-4">
                      <span className="text-3xl font-bold leading-none">{d.score}</span>
                      <div className="text-xs text-muted-foreground">
                        {b.rejected_reason ? <p className="text-destructive">Rejected: {String(b.rejected_reason)}</p>
                          : Object.entries(BREAKDOWN_LABELS)
                            .filter(([k]) => typeof b[k] === "number" && b[k] !== 0)
                            .map(([k, l]) => <p key={k}>{l}: {Number(b[k]) > 0 ? "+" : ""}{String(b[k])}</p>)}
                      </div>
                    </div>
                  )}
                  {d.match_reasons.map((r, i) => <p key={i} className="text-sm">{r}</p>)}
                </Section>

                {d.mandatory_findings.length > 0 && (
                  <Section title="Mandatory skills">
                    <ul className="space-y-2">
                      {d.mandatory_findings.map((f, i) => (
                        <li key={i} className="flex gap-2 text-sm">
                          {f.match === "present" ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                            : f.match === "related" ? <Minus className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                            : <X className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />}
                          <div>
                            <p>
                              <span className="font-medium">{f.skill}</span>
                              {f.match === "related" && f.related_skill && <span className="text-amber-700"> — similar: {f.related_skill}</span>}
                              {f.match === "absent" && <span className="text-red-700"> — missing</span>}
                              {f.strength && f.strength !== "none" && <Badge variant="outline" className="ml-2 text-[10px] capitalize">{f.strength}</Badge>}
                            </p>
                            {f.evidence && <p className="text-xs text-muted-foreground">{f.evidence}</p>}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </Section>
                )}

                {d.preferred_findings.length > 0 && (
                  <Section title="Preferred skills">
                    <div className="flex flex-wrap gap-1.5">
                      {d.preferred_findings.map((f, i) => (
                        <Badge key={i} variant={f.present ? "secondary" : "outline"} className={f.present ? "" : "text-muted-foreground line-through"}>
                          {f.skill}
                        </Badge>
                      ))}
                    </div>
                  </Section>
                )}

                {d.skills.length > 0 && (
                  <Section title="Skills on profile">
                    <div className="flex flex-wrap gap-1.5">
                      {d.skills.map((s, i) => <Badge key={i} variant="outline" className="font-normal">{s}</Badge>)}
                    </div>
                  </Section>
                )}

                {d.experiences.length > 0 && (
                  <Section title="Experience">
                    <ol className="space-y-3 border-l pl-4">
                      {d.experiences.map((e, i) => (
                        <li key={i} className="text-sm">
                          <p className="font-medium">
                            {pick(e, ["title", "designation", "role"]) || "Role"}
                            {pick(e, ["company", "organization", "employer"]) && <span className="font-normal"> @ {pick(e, ["company", "organization", "employer"])}</span>}
                            {e.is_current === true && <Badge variant="secondary" className="ml-2 text-[10px]">Current</Badge>}
                          </p>
                          <p className="text-xs text-muted-foreground">{pick(e, ["duration", "period", "dates", "tenure", "from"])}</p>
                          {pick(e, ["description", "summary"]) && <p className="mt-1 text-xs">{pick(e, ["description", "summary"])}</p>}
                        </li>
                      ))}
                    </ol>
                  </Section>
                )}

                {d.education.length > 0 && (
                  <Section title="Education">
                    <ul className="space-y-1.5 text-sm">
                      {d.education.map((e, i) => (
                        <li key={i}>
                          <span className="font-medium">{pick(e, ["degree", "course", "qualification"]) || "Degree"}</span>
                          {pick(e, ["institute", "institution", "college", "university"]) && <span> — {pick(e, ["institute", "institution", "college", "university"])}</span>}
                          {pick(e, ["year", "passing_year", "duration"]) && <span className="text-muted-foreground"> ({pick(e, ["year", "passing_year", "duration"])})</span>}
                        </li>
                      ))}
                    </ul>
                  </Section>
                )}

                {d.headline && (
                  <Section title="Headline">
                    <p className="text-sm">{d.headline}</p>
                  </Section>
                )}

                <Separator />
                <Section title="History">
                  <ul className="space-y-1.5 text-sm">
                    <li className="text-muted-foreground">Found on {d.source || "Naukri"} · {new Date(d.created_at).toLocaleString()}</li>
                    {d.status_history.map((h, i) => (
                      <li key={i}>
                        <span className="capitalize font-medium">{label(h.status)}</span>
                        <span className="text-muted-foreground"> by {h.by_name} · {new Date(h.at).toLocaleString()}</span>
                        {h.note && <p className="text-xs text-muted-foreground">“{h.note}”</p>}
                      </li>
                    ))}
                  </ul>
                </Section>
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
