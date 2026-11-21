"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { createSourcingJd } from "@/lib/api/sourcing";
import { Loader2, Sparkles, Upload, X } from "lucide-react";
import { toast } from "sonner";

const MAX_FILE = 15 * 1024 * 1024;
// Same minimum as the backend (sourcing/service.py MIN_JD_CHARS): shorter text is a title or a note, not a JD.
const MIN_JD_CHARS = 80;

export function NewJdDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [jdText, setJdText] = useState("");
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const pasted = jdText.trim().length;
  const pastedIsJd = pasted >= MIN_JD_CHARS;

  const submit = async () => {
    if (!pasted && !jdFile) return toast.error("Paste the job description or upload a PDF/DOCX");
    if (pasted && !pastedIsJd && !jdFile) {
      return toast.error(`The job description is too short (${pasted} of at least ${MIN_JD_CHARS} characters). Paste the full text or upload a PDF/DOCX.`);
    }
    setSubmitting(true);
    try {
      const created = await createSourcingJd({ title, jd_text: jdText, jd_file: jdFile });
      toast.success("Analyzing the JD…");
      onOpenChange(false);
      router.push(`/hiring/${created.id}`);
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Failed to create");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!submitting) onOpenChange(o); }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New hiring flow</DialogTitle>
          <DialogDescription>
            SkillMate reads the JD, sources matching profiles from Naukri (or LinkedIn), then runs the Level 1 exam automatically.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Title <span className="text-xs font-normal text-muted-foreground">optional</span></Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Python backend — Chennai" maxLength={120} />
          </div>
          <div className="space-y-2">
            <Label>Job description <span className="text-red-500">*</span></Label>
            <Textarea value={jdText} onChange={(e) => setJdText(e.target.value)} rows={10} placeholder="Paste the job description here…" />
            <div className="flex items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  if (f && f.size > MAX_FILE) {
                    toast.error("File must be under 15 MB");
                    e.target.value = "";
                    return;
                  }
                  setJdFile(f);
                }}
              />
              <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload className="mr-2 h-4 w-4" /> …or upload PDF / DOCX
              </Button>
              {jdFile && (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  {jdFile.name}
                  <button type="button" onClick={() => { setJdFile(null); if (fileRef.current) fileRef.current.value = ""; }}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </span>
              )}
            </div>
            {pasted > 0 && jdFile && (
              <p className="text-xs text-muted-foreground">
                {pastedIsJd
                  ? "Pasted text is used; the uploaded file is ignored."
                  : `The pasted text is too short to be a job description (${pasted} of ${MIN_JD_CHARS} characters), so the uploaded file is used.`}
              </p>
            )}
            {pasted > 0 && !pastedIsJd && !jdFile && (
              <p className="text-xs text-amber-600">{pasted} of at least {MIN_JD_CHARS} characters — paste the full job description or upload a PDF/DOCX.</p>
            )}
          </div>
          <div className="flex justify-end">
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
              Analyze JD
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
