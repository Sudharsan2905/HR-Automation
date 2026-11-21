"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, Pencil } from "lucide-react";
import type { SourcingSearchPlan } from "@/types/sourcing";

const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));

export function SearchPlanCard({ plan, onSave }: { plan: SourcingSearchPlan; onSave: (p: SourcingSearchPlan) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ primary: "", narrowed: "", expMin: "", expMax: "", ctc: "", locations: "" });

  const save = async (next: SourcingSearchPlan) => {
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const startEdit = () => {
    setForm({
      primary: plan.primary_keywords,
      narrowed: plan.narrowed_keywords,
      expMin: plan.experience_min?.toString() ?? "",
      expMax: plan.experience_max?.toString() ?? "",
      ctc: plan.ctc_max_lacs?.toString() ?? "",
      locations: plan.locations.join(", "),
    });
    setEditing(true);
  };

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">Candidate search</CardTitle>
        {!editing && <Button variant="ghost" size="sm" onClick={startEdit}><Pencil className="mr-1 h-3.5 w-3.5" /> Edit</Button>}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!editing ? (
          <>
            <div className="space-y-1">
              <p className="text-muted-foreground">Primary (mandatory skills only)</p>
              <p className="break-words rounded bg-muted px-2 py-1.5 font-mono text-xs">{plan.primary_keywords || "—"}</p>
            </div>
            <div className="space-y-1">
              <p className="text-muted-foreground">Narrowed (adds a preferred skill — smaller pool)</p>
              <p className="break-words rounded bg-muted px-2 py-1.5 font-mono text-xs">{plan.narrowed_keywords || "—"}</p>
            </div>
            <label className="flex items-center gap-2">
              <Switch
                checked={plan.use_narrowed}
                disabled={saving}
                onCheckedChange={(v) => save({ ...plan, use_narrowed: v })}
              />
              <span>Search with the narrowed string</span>
            </label>
            <p className="text-xs text-muted-foreground">
              Filters: {plan.experience_min ?? "?"}–{plan.experience_max ?? "?"} yrs · {plan.locations.join(", ") || "any location"}
              {plan.ctc_max_lacs != null ? ` · up to ${plan.ctc_max_lacs} L` : ""}
            </p>
          </>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1"><Label>Primary keywords</Label><Textarea rows={3} className="font-mono text-xs" value={form.primary} onChange={set("primary")} /></div>
            <div className="space-y-1"><Label>Narrowed keywords</Label><Textarea rows={3} className="font-mono text-xs" value={form.narrowed} onChange={set("narrowed")} /></div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1"><Label>Exp min</Label><Input value={form.expMin} onChange={set("expMin")} /></div>
              <div className="space-y-1"><Label>Exp max</Label><Input value={form.expMax} onChange={set("expMax")} /></div>
              <div className="space-y-1"><Label>CTC max (L)</Label><Input value={form.ctc} onChange={set("ctc")} /></div>
            </div>
            <div className="space-y-1"><Label>Locations <span className="text-xs font-normal text-muted-foreground">comma separated</span></Label><Input value={form.locations} onChange={set("locations")} /></div>
            <p className="text-xs text-muted-foreground">Saving restarts paging from page 1 on Naukri and LinkedIn. Profiles already found are never shown twice.</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(false)} disabled={saving}>Cancel</Button>
              <Button
                disabled={saving}
                onClick={() => save({
                  ...plan,
                  primary_keywords: form.primary.trim(),
                  narrowed_keywords: form.narrowed.trim(),
                  experience_min: num(form.expMin),
                  experience_max: num(form.expMax),
                  ctc_max_lacs: num(form.ctc),
                  locations: form.locations.split(",").map((x) => x.trim()).filter(Boolean),
                })}
              >
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
