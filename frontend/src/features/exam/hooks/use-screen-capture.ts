"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { takeScreenStream } from "../lib/stream-store";

const MAX_WIDTH = 1280;
const JPEG_QUALITY = 0.6;

type DisplayTrackSettings = MediaTrackSettings & { displaySurface?: string };

/** Screen-share stream manager (monitor-only) that also grabs JPEG frames for screenshots. */
export function useScreenCapture({ shouldInitialize }: { shouldInitialize: boolean }) {
  const streamRef = useRef<MediaStream | null>(null);
  const videoElRef = useRef<HTMLVideoElement | null>(null);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const capturingRef = useRef(false);
  const initializedRef = useRef(false);

  const stopScreenCapture = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoElRef.current) {
      videoElRef.current.srcObject = null;
      videoElRef.current = null;
    }
    capturingRef.current = false;
    setIsCapturing(false);
  }, []);

  const setupStream = useCallback(
    async (stream: MediaStream): Promise<boolean> => {
      try {
        const video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        await video.play();
        videoElRef.current = video;
        stream.getVideoTracks()[0]?.addEventListener("ended", stopScreenCapture);
        streamRef.current = stream;
        capturingRef.current = true;
        setIsCapturing(true);
        return true;
      } catch {
        stream.getTracks().forEach((t) => t.stop());
        return false;
      }
    },
    [stopScreenCapture]
  );

  // Adopt a stream pre-acquired on the instructions page once the gate opens.
  const adopted = useRef(false);
  useEffect(() => {
    if (!shouldInitialize || adopted.current) return;
    adopted.current = true;
    void (async () => {
      const stored = takeScreenStream();
      if (stored) await setupStream(stored);
      initializedRef.current = true;
      setIsInitialized(true);
    })();
  }, [shouldInitialize, setupStream]);

  // Re-validate the stream when the tab returns / network reconnects.
  useEffect(() => {
    const revalidate = () => {
      if (!initializedRef.current || !capturingRef.current) return;
      const track = streamRef.current?.getVideoTracks()[0];
      const surface = (track?.getSettings() as DisplayTrackSettings | undefined)?.displaySurface;
      if (!track || track.readyState !== "live" || (surface !== undefined && surface !== "monitor"))
        stopScreenCapture();
    };
    const onVisibility = () => {
      if (!document.hidden) revalidate();
    };
    window.addEventListener("online", revalidate);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("online", revalidate);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [stopScreenCapture]);

  const startScreenCapture = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) return true;
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "monitor", frameRate: 5 } as MediaTrackConstraints,
        audio: false,
      });
      const settings = stream.getVideoTracks()[0]?.getSettings() as DisplayTrackSettings;
      if (settings?.displaySurface !== undefined && settings.displaySurface !== "monitor") {
        stream.getTracks().forEach((t) => t.stop());
        return false;
      }
      return setupStream(stream);
    } catch {
      return false;
    }
  }, [setupStream]);

  const captureFrame = useCallback(async (): Promise<Blob | null> => {
    const video = videoElRef.current;
    if (!video?.videoWidth) return null;
    const scale = Math.min(1, MAX_WIDTH / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
  }, []);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return {
    isCapturing,
    isInitialized,
    startScreenCapture,
    captureFrame,
    stopScreenCapture,
    streamRef,
  };
}
