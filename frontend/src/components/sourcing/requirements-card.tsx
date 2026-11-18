"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, Pencil } from "lucide-react";
import type { SkillSpec, SourcingRequirements } from "@/types/sourcing";

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));

// One skill per line: "Node.js: Node, NodeJS"
const skillsToText = (skills: SkillSpec[]) =>
  skills.map((s) => (s.variants.length ? `${s.name}: ${s.variants.join(", ")}` : s.name)).join("\n");
const textToSkills = (text: string): SkillSpec[] =>
  text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [name, rest] = line.split(":");
    return { name: name.trim(), variants: rest ? list(rest) : [] };
  });

function SkillChips({ skills }: { skills: SkillSpec[] }) {
  if (!skills.length) return <span className="text-sm text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {skills.map((s) => (
        <Badge key={s.name} variant="outline" title={s.variants.join(", ")}>{s.name}</Badge>
      ))}
    </div>
  );
}

export function RequirementsCard({ requirements, onSave }: {
  requirements: SourcingRequirements;
  onSave: (req: SourcingRequirements) => Promise<void>;
}) {
  const r = requirements;
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    role_title: "", mandatory: "", preferred: "", expMin: "", expMax: "", ctc: "", locations: "", target: "", avoid: "",
  });

  const startEdit = () => {
    setForm({
      role_title: r.role_title,
      mandatory: skillsToText(r.mandatory_skills),
      preferred: skillsToText(r.preferred_skills),
      expMin: r.experience_min_years?.toString() ?? "",
      expMax: r.experience_max_years?.toString() ?? "",
      ctc: r.ctc_max_lacs?.toString() ?? "",
      locations: r.locations.join(", "),
      target: r.target_companies.join(", "),
      avoid: r.avoid_companies.join(", "),
    });
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave({
        role_title: form.role_title.trim(),
        mandatory_skills: textToSkills(form.mandatory),
        preferred_skills: textToSkills(form.preferred),
        experience_min_years: num(form.expMin),
        experience_max_years: num(form.expMax),
        ctc_max_lacs: num(form.ctc),
        locations: list(form.locations),
        target_companies: list(form.target),
        avoid_companies: list(form.avoid),
      });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const range = (a: number | null, b: number | null, unit: string) =>
    a == null && b == null ? "—" : `${a ?? "?"}–${b ?? "?"} ${unit}`;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">Requirements</CardTitle>
        {!editing && <Button variant="ghost" size="sm" onClick={startEdit}><Pencil className="mr-1 h-3.5 w-3.5" /> Edit</Button>}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!editing ? (
          <>
            <div><span className="text-muted-foreground">Role: </span>{r.role_title || "—"}</div>
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              <span><span className="text-muted-foreground">Experience: </span>{range(r.experience_min_years, r.experience_max_years, "yrs")}</span>
              <span><span className="text-muted-foreground">CTC max: </span>{r.ctc_max_lacs != null ? `${r.ctc_max_lacs} L` : "—"}</span>
              <span><span className="text-muted-foreground">Location: </span>{r.locations.join(", ") || "—"}</span>
            </div>
            <div className="space-y-1"><p className="text-muted-foreground">Mandatory skills</p><SkillChips skills={r.mandatory_skills} /></div>
            <div className="space-y-1"><p className="text-muted-foreground">Preferred skills</p><SkillChips skills={r.preferred_skills} /></div>
            {(r.target_companies.length > 0 || r.avoid_companies.length > 0) && (
              <div className="flex flex-wrap gap-x-6 gap-y-1">
                {r.target_companies.length > 0 && <span><span className="text-muted-foreground">Target: </span>{r.target_companies.join(", ")}</span>}
                {r.avoid_companies.length > 0 && <span><span className="text-muted-foreground">Avoid: </span>{r.avoid_companies.join(", ")}</span>}
              </div>
            )}
          </>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1"><Label>Role</Label><Input value={form.role_title} onChange={set("role_title")} /></div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1"><Label>Exp min (yrs)</Label><Input value={form.expMin} onChange={set("expMin")} /></div>
              <div className="space-y-1"><Label>Exp max (yrs)</Label><Input value={form.expMax} onChange={set("expMax")} /></div>
              <div className="space-y-1"><Label>CTC max (L)</Label><Input value={form.ctc} onChange={set("ctc")} /></div>
            </div>
            <div className="space-y-1">
              <Label>Mandatory skills <span className="text-xs font-normal text-muted-foreground">one per line, e.g. &quot;Node.js: Node, NodeJS&quot;</span></Label>
              <Textarea rows={4} value={form.mandatory} onChange={set("mandatory")} />
            </div>
            <div className="space-y-1"><Label>Preferred skills</Label><Textarea rows={3} value={form.preferred} onChange={set("preferred")} /></div>
            <div className="space-y-1"><Label>Locations <span className="text-xs font-normal text-muted-foreground">comma separated</span></Label><Input value={form.locations} onChange={set("locations")} /></div>
            <div className="space-y-1"><Label>Target companies</Label><Input value={form.target} onChange={set("target")} /></div>
            <div className="space-y-1"><Label>Avoid companies</Label><Input value={form.avoid} onChange={set("avoid")} /></div>
            <p className="text-xs text-muted-foreground">Saving re-scores profiles that haven&apos;t been shown yet.</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(false)} disabled={saving}>Cancel</Button>
              <Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
