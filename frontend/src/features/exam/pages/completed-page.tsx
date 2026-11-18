"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth-store";
import { ExamHeader } from "../components/exam-header";
import { useExamAuth } from "../hooks/use-exam-auth";
import { examPaths } from "../lib/constants";
import { clearAssessmentSession, isAssessmentDone } from "../lib/session-storage";

export function CompletedPage({ shareLink }: { shareLink: string }) {
  const router = useRouter();
  const { mounted, candidateName } = useExamAuth();
  const valid = mounted && isAssessmentDone(shareLink);

  useEffect(() => {
    // No completion marker (direct URL / history abuse) -> back to entry.
    if (mounted && !valid) router.replace(examPaths.entry(shareLink));
  }, [mounted, valid, router, shareLink]);

  if (!valid)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );

  return (
    <div className="flex min-h-screen flex-col bg-muted/30">
      <ExamHeader candidateName={candidateName} />
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-md rounded-xl border bg-background p-8 text-center shadow-sm">
          <CheckCircle2 className="mx-auto size-14 text-emerald-500" />
          <h1 className="mt-4 text-2xl font-semibold">Assessment Submitted!</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Thank you for completing the assessment. Your responses have been recorded and will be reviewed by the hiring team.
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            You will be contacted if you are shortlisted for the next stage. You may now close this window.
          </p>
          <Button
            variant="outline"
            className="mt-6"
            onClick={() => {
              clearAssessmentSession(shareLink);
              useAuthStore.getState().logout();
              router.replace(examPaths.entry(shareLink));
            }}
          >
            Exit
          </Button>
        </div>
      </div>
    </div>
  );
}
