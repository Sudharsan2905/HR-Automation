"use client";

import { useSyncExternalStore } from "react";
import { useAuthStore } from "@/stores/auth-store";

const noopSubscribe = () => () => {};

/** True only after hydration, so persisted auth state never causes a markup mismatch. */
export function useMounted() {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}

export function useExamAuth() {
  const mounted = useMounted();
  const token = useAuthStore((s) => s.token);
  const role = useAuthStore((s) => s.role);
  const email = useAuthStore((s) => s.email);
  const fullName = useAuthStore((s) => s.fullName);
  return {
    mounted,
    token,
    email,
    isCandidate: mounted && !!token && role === "candidate",
    candidateName: fullName || email || undefined,
  };
}
