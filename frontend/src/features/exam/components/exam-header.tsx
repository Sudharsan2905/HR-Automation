import { ShieldCheck } from "lucide-react";

export function ExamHeader({ candidateName }: { candidateName?: string | null }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b bg-background px-4 sm:px-6">
      <div className="flex items-center gap-2 font-semibold">
        <ShieldCheck className="size-5 text-primary" />
        <span>SkillMate</span>
        <span className="text-sm font-normal text-muted-foreground">Assessment</span>
      </div>
      {candidateName ? (
        <span className="text-sm text-muted-foreground">{candidateName}</span>
      ) : null}
    </header>
  );
}
