"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Ban, Link2Off, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { candidateLogin } from "@/lib/api/auth";
import {
  EXAM_KEY_EXPIRED_MESSAGE,
  examErrorMessage,
  getExamAssessment,
  getExamSubmissionStatus,
  isExamUnauthorized,
} from "@/lib/api/level1-exam";
import { useAuthStore } from "@/stores/auth-store";
import { StatusScreen } from "../components/status-screen";
import { useExamAuth } from "../hooks/use-exam-auth";
import { examPaths } from "../lib/constants";
import { markAssessmentDone } from "../lib/session-storage";

type View =
  | { kind: "checking" }
  | { kind: "login"; message?: string }
  | { kind: "invalid"; message: string }
  | { kind: "blocked"; title: string; description: string };

function LoginForm({ message, onDone }: { message?: string; onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState(message ?? "");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await candidateLogin({ email: email.trim(), access_key: key.trim() });
      useAuthStore.getState().setAuth(res.access_token, res.role, email.trim());
      onDone();
    } catch (err) {
      setError(examErrorMessage(err, "Invalid email or access key"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border bg-background p-8 shadow-sm">
        <div>
          <h1 className="text-xl font-semibold">SkillMate Assessment</h1>
          <p className="mt-1 text-sm text-muted-foreground">Enter your email and access key to begin.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="exam-email">Email</Label>
          <Input id="exam-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="exam-key">Access key</Label>
          <Input id="exam-key" type="password" required value={key} onChange={(e) => setKey(e.target.value)} />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : null}Continue
        </Button>
      </form>
    </div>
  );
}

export function EntryPage({ shareLink }: { shareLink: string }) {
  const router = useRouter();
  const expired = useSearchParams().get("expired") === "1";
  const { mounted, isCandidate } = useExamAuth();
  const [view, setView] = useState<View>({ kind: "checking" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!isCandidate) return;
    let cancelled = false;
    const run = async () => {
      try {
        await getExamAssessment(shareLink);
      } catch (e) {
        if (cancelled) return;
        if (isExamUnauthorized(e)) return setView({ kind: "login", message: EXAM_KEY_EXPIRED_MESSAGE });
        return setView({ kind: "invalid", message: examErrorMessage(e, "This link is not valid.") });
      }
      let status: string | undefined;
      try {
        status = (await getExamSubmissionStatus(shareLink))?.status;
      } catch (e) {
        if (isExamUnauthorized(e)) return !cancelled && setView({ kind: "login", message: EXAM_KEY_EXPIRED_MESSAGE });
      }
      if (cancelled) return;
      if (status === "completed") {
        markAssessmentDone(shareLink);
        return router.replace(examPaths.completed(shareLink));
      }
      if (status === "terminated")
        return setView({
          kind: "blocked",
          title: "Session Terminated",
          description: "Your session was ended by an administrator. Please contact them for re-access.",
        });
      if (status === "malpractice")
        return setView({
          kind: "blocked",
          title: "Assessment Terminated",
          description:
            "Your assessment was terminated due to repeated violations. Please contact the administrator for re-access.",
        });
      router.replace(examPaths.instructions(shareLink));
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [isCandidate, shareLink, router, attempt]);

  if (!mounted) return null;
  if (!isCandidate)
    return (
      <LoginForm
        message={expired ? EXAM_KEY_EXPIRED_MESSAGE : view.kind === "login" ? view.message : undefined}
        onDone={() => setAttempt((n) => n + 1)}
      />
    );
  if (view.kind === "invalid")
    return <StatusScreen icon={<Link2Off className="size-6" />} title="Invalid Link" description={view.message} />;
  if (view.kind === "blocked")
    return <StatusScreen icon={<Ban className="size-6" />} title={view.title} description={view.description} />;
  if (view.kind === "login")
    return <LoginForm message={view.message} onDone={() => setAttempt((n) => n + 1)} />;
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="size-8 animate-spin text-muted-foreground" />
    </div>
  );
}
