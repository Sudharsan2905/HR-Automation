"use client";

import { CheckCircle, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ConditionCardProps {
  label: string;
  met: boolean;
  action?: React.ReactNode;
}

export function ConditionCard({ label, met, action }: ConditionCardProps) {
  return (
    <div className={cn(
      "flex items-center justify-between rounded-lg border p-4",
      met ? "border-green-500/30 bg-green-500/5" : "border-white/10 bg-white/5"
    )}>
      <div className="flex items-center gap-3">
        {met ? (
          <CheckCircle className="h-5 w-5 text-green-500" />
        ) : (
          <XCircle className="h-5 w-5 text-white/30" />
        )}
        <span className={met ? "text-green-400" : "text-white/60"}>{label}</span>
      </div>
      {!met && action}
    </div>
  );
}
