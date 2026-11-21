"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileQuestion, Loader2 } from "lucide-react";
import { getMyExamAssessment, isExamUnauthorized } from "@/lib/api/level1-exam";
import { useAuthStore } from "@/stores/auth-store";
import { StatusScreen } from "../components/status-screen";
import { useExamAuth } from "../hooks/use-exam-auth";
import { examPaths } from "../lib/constants";

/** /exam: signed-in candidates go straight to their assessment; everyone else signs in first. */
export function HomePage() {
  const router = useRouter();
  const { mounted, isCandidate } = useExamAuth();
  const [none, setNone] = useState(false);

  useEffect(() => {
    if (!mounted) return;
    if (!isCandidate) {
      router.replace("/login?next=/exam");
      return;
    }
    let cancelled = false;
    getMyExamAssessment()
      .then((res) => {
        if (cancelled) return;
        if (res.share_link) router.replace(examPaths.entry(res.share_link));
        else setNone(true);
      })
      .catch((e) => {
        if (cancelled) return;
        if (isExamUnauthorized(e)) router.replace("/login?next=/exam");
        else setNone(true);
      });
    return () => {
      cancelled = true;
    };
  }, [mounted, isCandidate, router]);

  if (none)
    return (
      <StatusScreen
        icon={<FileQuestion className="size-6" />}
        title="No Assessment Found"
        description="No assessment is assigned to this account yet. Use the link from your invitation email, or contact the hiring team."
        actionLabel="Sign out"
        onAction={() => {
          useAuthStore.getState().logout();
          router.replace("/login");
        }}
      />
    );
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="size-8 animate-spin text-muted-foreground" />
    </div>
  );
}
