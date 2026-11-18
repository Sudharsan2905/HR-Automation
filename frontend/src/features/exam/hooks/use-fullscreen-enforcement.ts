"use client";

import { useCallback, useEffect, useRef } from "react";

const FS_EVENTS = [
  "fullscreenchange",
  "webkitfullscreenchange",
  "mozfullscreenchange",
  "MSFullscreenChange",
] as const;

export async function requestDocumentFullscreen(): Promise<void> {
  if (document.fullscreenElement) return;
  try {
    await document.documentElement.requestFullscreen({ navigationUI: "hide" });
  } catch {
    /* browser may deny — recovery modal handles re-entry */
  }
}

/**
 * Enforces fullscreen. `onExit` fires (after a 1s grace) when the candidate leaves
 * fullscreen; `onBlockRequired` fires when the initial request is denied (no violation).
 */
export function useFullscreenEnforcement({
  enabled,
  onExit,
  onBlockRequired,
}: {
  enabled: boolean;
  onExit?: (description: string) => void;
  onBlockRequired?: () => void;
}) {
  const onExitRef = useRef(onExit);
  const onBlockRef = useRef(onBlockRequired);
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    onExitRef.current = onExit;
    onBlockRef.current = onBlockRequired;
  });

  const requestFullscreen = useCallback(() => requestDocumentFullscreen(), []);

  useEffect(() => {
    return () => {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    const handleChange = () => {
      if (document.fullscreenElement) {
        if (exitTimer.current !== null) {
          clearTimeout(exitTimer.current);
          exitTimer.current = null;
        }
        return;
      }
      if (exitTimer.current !== null) return;
      exitTimer.current = setTimeout(() => {
        exitTimer.current = null;
        if (!document.fullscreenElement) onExitRef.current?.("Candidate exited fullscreen mode");
      }, 1_000);
    };

    FS_EVENTS.forEach((ev) => document.addEventListener(ev, handleChange));

    const start = setTimeout(() => {
      void (async () => {
        if (cancelled) return;
        await requestDocumentFullscreen();
        if (!cancelled && !document.fullscreenElement) onBlockRef.current?.();
      })();
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(start);
      if (exitTimer.current !== null) {
        clearTimeout(exitTimer.current);
        exitTimer.current = null;
      }
      FS_EVENTS.forEach((ev) => document.removeEventListener(ev, handleChange));
    };
  }, [enabled]);

  return { requestFullscreen };
}
