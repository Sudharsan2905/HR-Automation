"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { decodeJwt } from "@/lib/utils";
import { toast } from "sonner";

export function useCountdown() {
  const token = useAuthStore((s) => s.token);
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();
  const [remaining, setRemaining] = useState(0);
  const expiredRef = useRef(false);

  useEffect(() => {
    if (!token) return;
    const payload = decodeJwt(token);
    if (!payload) return;
    expiredRef.current = false;

    const update = () => {
      const now = Math.floor(Date.now() / 1000);
      const left = Math.max(0, payload.exp - now);
      setRemaining(left);

      if (left <= 0 && !expiredRef.current) {
        expiredRef.current = true;
        toast.error("Session expired. Time is up.");
        logout();
        router.push("/login");
      }
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [token, logout, router]);

  return remaining;
}
