"use client";

import { useEffect, useState, useRef } from "react";

interface CaptionOverlayProps {
  text: string | null;
  /** Speed in ms per character */
  speed?: number;
}

export function CaptionOverlay({ text, speed = 50 }: CaptionOverlayProps) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);
  const prevTextRef = useRef<string | null>(null);

  useEffect(() => {
    if (!text) {
      setDisplayed("");
      setDone(false);
      prevTextRef.current = null;
      return;
    }

    // Only restart typewriter when text actually changes
    if (text === prevTextRef.current) return;
    prevTextRef.current = text;

    setDisplayed("");
    setDone(false);

    let i = 0;
    const timer = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(timer);
        setDone(true);
      }
    }, speed);

    return () => clearInterval(timer);
  }, [text, speed]);

  if (!text) return null;

  return (
    <div className="flex-1 min-w-0">
      <div className="bg-black/60 backdrop-blur-sm rounded-lg px-4 py-3">
        <p className="text-white text-sm leading-relaxed">
          {displayed}
          {!done && <span className="animate-pulse text-[#00e5ff]">|</span>}
        </p>
      </div>
    </div>
  );
}
