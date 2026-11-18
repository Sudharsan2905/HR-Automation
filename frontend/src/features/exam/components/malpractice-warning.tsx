"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useExamStore } from "@/stores/exam-store";

export function MalpracticeWarning() {
  const visible = useExamStore((s) => s.isWarningVisible);
  const message = useExamStore((s) => s.warningMessage);
  const count = useExamStore((s) => s.malpracticeCount);
  const limit = useExamStore((s) => s.malpracticeLimit);
  const dismiss = useExamStore((s) => s.dismissWarning);

  useEffect(() => {
    if (!visible) return;
    const t = setTimeout(dismiss, 5000);
    return () => clearTimeout(t);
  }, [visible, dismiss]);

  if (!visible) return null;
  return (
    <div
      role="alert"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
    >
      <div className="w-full max-w-sm rounded-xl bg-background p-6 text-center shadow-lg">
        <AlertTriangle className="mx-auto size-10 text-amber-500" />
        <h3 className="mt-2 text-lg font-semibold">Warning</h3>
        <p className="mt-1 text-sm text-muted-foreground">{message}</p>
        <p className="mt-2 text-xs font-medium text-destructive">
          {count} / {limit} violations
        </p>
        <Button className="mt-4" variant="outline" onClick={dismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}
