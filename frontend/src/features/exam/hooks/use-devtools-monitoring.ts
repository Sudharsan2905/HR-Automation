"use client";

import { useEffect, useRef, type RefObject } from "react";
import { DEVTOOLS_SIZE_THRESHOLD } from "../lib/constants";

const COOLDOWN_MS = 10_000;

/** Resize-driven devtools detection, armed only while the exam is active. */
export function useDevtoolsMonitoring({
  enabled,
  examActiveRef,
  onViolation,
}: {
  enabled: boolean;
  examActiveRef: RefObject<boolean>;
  onViolation: (description: string) => void;
}) {
  const last = useRef(0);
  const cb = useRef(onViolation);
  useEffect(() => {
    cb.current = onViolation;
  });

  useEffect(() => {
    if (!enabled) return;
    const check = () => {
      if (!examActiveRef.current) return;
      const delta = Math.max(
        window.outerWidth - window.innerWidth,
        window.outerHeight - window.innerHeight
      );
      if (delta <= DEVTOOLS_SIZE_THRESHOLD) return;
      const now = performance.now();
      if (now - last.current <= COOLDOWN_MS) return;
      last.current = now;
      cb.current(`Browser developer tools were opened (window size delta: ${delta}px)`);
    };
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [enabled, examActiveRef]);
}
