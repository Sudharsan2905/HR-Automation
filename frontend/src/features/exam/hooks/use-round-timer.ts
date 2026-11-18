"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const LOW_TIME_THRESHOLD_SECONDS = 120;

function pad(n: number) {
  return n.toString().padStart(2, "0");
}

/**
 * Countdown for a round. Ticks only while `active` (pauses on network loss / hold)
 * and calls `onExpired` exactly once at zero. `timeLeftRef` always has the live value.
 */
export function useRoundTimer({
  active,
  onExpired,
}: {
  active: boolean;
  onExpired: () => void;
}) {
  const [timeLeft, setTimeLeftState] = useState(0);
  const timeLeftRef = useRef(0);
  const onExpiredRef = useRef(onExpired);

  useEffect(() => {
    onExpiredRef.current = onExpired;
  });

  const setTimeLeft = useCallback((seconds: number) => {
    timeLeftRef.current = seconds;
    setTimeLeftState(seconds);
  }, []);

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      const next = timeLeftRef.current - 1;
      if (next <= 0) {
        timeLeftRef.current = 0;
        setTimeLeftState(0);
        clearInterval(id);
        onExpiredRef.current();
        return;
      }
      timeLeftRef.current = next;
      setTimeLeftState(next);
    }, 1000);
    return () => clearInterval(id);
  }, [active]);

  const h = Math.floor(timeLeft / 3600);
  const m = Math.floor((timeLeft % 3600) / 60);
  const s = timeLeft % 60;

  return {
    timeLeft,
    setTimeLeft,
    timeLeftRef,
    isLowTime: timeLeft < LOW_TIME_THRESHOLD_SECONDS,
    formattedTime: { hh: pad(h), mm: pad(m), ss: pad(s) },
  };
}
