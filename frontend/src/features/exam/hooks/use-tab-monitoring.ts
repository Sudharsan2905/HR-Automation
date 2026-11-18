"use client";

import { useEffect, useRef, type RefObject } from "react";

const GRACE_MS = 1_000;
const LOCK_MS = 1_000;

/**
 * Detects tab switches (visibility hidden > 1s) and focus loss while still visible
 * in fullscreen (OS notification / DND bypass).
 */
export function useTabMonitoring({
  enabled,
  examActiveRef,
  isPermissionFlowActiveRef,
  onTabSwitch,
  onFocusViolation,
}: {
  enabled: boolean;
  examActiveRef: RefObject<boolean>;
  isPermissionFlowActiveRef: RefObject<boolean>;
  onTabSwitch: (description: string) => void;
  onFocusViolation: (description: string) => void;
}) {
  const onTabRef = useRef(onTabSwitch);
  const onFocusRef = useRef(onFocusViolation);
  useEffect(() => {
    onTabRef.current = onTabSwitch;
    onFocusRef.current = onFocusViolation;
  });

  useEffect(() => {
    if (!enabled) return;
    let tabTimer: ReturnType<typeof setTimeout> | null = null;
    let focusTimer: ReturnType<typeof setTimeout> | null = null;
    let last = 0;

    const canFire = () => {
      if (!examActiveRef.current || isPermissionFlowActiveRef.current) return false;
      const now = performance.now();
      if (now - last <= LOCK_MS) return false;
      last = now;
      return true;
    };
    const cancelFocus = () => {
      if (focusTimer !== null) clearTimeout(focusTimer);
      focusTimer = null;
    };
    const cancelAll = () => {
      if (tabTimer !== null) clearTimeout(tabTimer);
      tabTimer = null;
      cancelFocus();
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        cancelFocus();
        if (tabTimer !== null || isPermissionFlowActiveRef.current) return;
        tabTimer = setTimeout(() => {
          tabTimer = null;
          if (canFire())
            onTabRef.current(
              "Candidate switched away from the assessment tab for more than 1 second"
            );
        }, GRACE_MS);
      } else {
        cancelAll();
      }
    };
    const onBlur = () => {
      if (document.visibilityState !== "visible") return;
      if (focusTimer !== null || isPermissionFlowActiveRef.current) return;
      focusTimer = setTimeout(() => {
        focusTimer = null;
        if (!document.fullscreenElement) return;
        if (canFire())
          onFocusRef.current(
            "Window focus lost during fullscreen assessment — possible notification interaction"
          );
      }, GRACE_MS);
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", cancelAll);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", cancelAll);
      cancelAll();
    };
  }, [enabled, examActiveRef, isPermissionFlowActiveRef]);
}
