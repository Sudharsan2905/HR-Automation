"use client";

import { useCountdown } from "@/hooks/use-countdown";
import { formatSeconds } from "@/lib/utils";
import { Clock } from "lucide-react";

export function SessionTimer() {
  const remaining = useCountdown();

  const isLow = remaining < 300; // less than 5 min

  return (
    <div className={`flex items-center gap-2 text-sm font-mono ${isLow ? "text-red-400" : "text-white/70"}`}>
      <Clock className="h-4 w-4" />
      {formatSeconds(remaining)}
    </div>
  );
}
