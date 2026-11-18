"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { Camera } from "lucide-react";
import { cn } from "@/lib/utils";

type Status = "checking" | "live" | "no-feed";

/** Camera preview with a brightness check that raises `onWarning` after sustained dark frames. */
export function VideoMonitor({
  videoRef,
  bindVideo,
  onWarning,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  bindVideo: (el: HTMLVideoElement | null) => void;
  onWarning?: () => void;
}) {
  const [status, setStatus] = useState<Status>("checking");
  const dark = useRef(0);
  const warnRef = useRef(onWarning);
  useEffect(() => {
    warnRef.current = onWarning;
  });

  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const check = () => {
      const video = videoRef.current;
      if (!ctx || !video || video.readyState < 2 || video.videoWidth === 0) {
        dark.current = 0;
        setStatus("no-feed");
        return;
      }
      ctx.drawImage(video, 0, 0, 32, 32);
      const { data } = ctx.getImageData(0, 0, 32, 32);
      let total = 0;
      for (let i = 0; i < data.length; i += 4)
        total += data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
      if (total / 1024 < 10) {
        dark.current += 1;
        if (dark.current >= 5) warnRef.current?.();
        setStatus("no-feed");
      } else {
        dark.current = 0;
        setStatus("live");
      }
    };
    const t0 = setTimeout(check, 0);
    const id = setInterval(check, 3000);
    return () => {
      clearTimeout(t0);
      clearInterval(id);
    };
  }, [videoRef]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Camera className="size-3.5" /> Camera
      </div>
      <div className="relative overflow-hidden rounded-lg bg-black">
        <video ref={bindVideo} autoPlay muted playsInline className="aspect-video w-full -scale-x-100 object-cover" />
        <span
          className={cn(
            "absolute top-2 right-2 rounded-full px-2 py-0.5 text-[10px] font-semibold",
            status === "live" && "bg-emerald-500 text-white",
            status === "no-feed" && "bg-destructive text-white",
            status === "checking" && "bg-muted text-muted-foreground"
          )}
        >
          {status === "live" ? "Live" : status === "no-feed" ? "No Feed" : "Checking"}
        </span>
      </div>
    </div>
  );
}
