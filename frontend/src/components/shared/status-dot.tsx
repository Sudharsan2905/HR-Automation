"use client";

import { Badge } from "@/components/ui/badge";
import { STATUS_COLORS } from "@/lib/constants";

interface StatusDotProps {
  status: string;
  label?: string;
}

export function StatusBadge({ status, label }: StatusDotProps) {
  const colors = STATUS_COLORS[status] || "bg-gray-100 text-gray-800";
  return (
    <Badge variant="secondary" className={colors}>
      {label || status.replace(/_/g, " ")}
    </Badge>
  );
}
