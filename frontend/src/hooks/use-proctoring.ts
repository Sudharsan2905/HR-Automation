"use client";

import { useEffect, useCallback, useRef } from "react";
import { useSessionStore } from "@/stores/session-store";

export function useProctoring() {
  const addWarning = useSessionStore((s) => s.addWarning);
  const warnings = useSessionStore((s) => s.warnings);
  const fullscreenRef = useRef(false);

  const enterFullscreen = useCallback(async () => {
    try {
      await document.documentElement.requestFullscreen();
      fullscreenRef.current = true;
    } catch {
      console.error("Fullscreen not supported");
    }
  }, []);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        addWarning();
      }
    };

    const handleFullscreenChange = () => {
      fullscreenRef.current = !!document.fullscreenElement;
      if (!document.fullscreenElement) {
        addWarning();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    document.addEventListener("fullscreenchange", handleFullscreenChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, [addWarning]);

  return { warnings, enterFullscreen, isFullscreen: fullscreenRef.current };
}
