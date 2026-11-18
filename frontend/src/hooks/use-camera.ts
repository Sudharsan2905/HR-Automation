"use client";

import { useEffect, useRef, useState, useCallback } from "react";

export function useCamera() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hardwareExists, setHardwareExists] = useState<boolean | null>(null);

  const detectHardware = useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const hasCamera = devices.some((d) => d.kind === "videoinput");
      if (!hasCamera) {
        setHardwareExists(false);
        return false;
      }
      // Probe the device — virtual cameras (OBS, etc.) fail here when not running
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      stream.getTracks().forEach((t) => t.stop());
      setHardwareExists(true);
      return true;
    } catch {
      setHardwareExists(false);
      return false;
    }
  }, []);

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      streamRef.current = stream;
      setActive(true);
      setError(null);
    } catch (err) {
      setError("Camera access denied");
      setActive(false);
      console.error("Camera error:", err);
    }
  }, []);

  // Attach stream to video element whenever ref or active state changes
  useEffect(() => {
    if (active && streamRef.current && videoRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  });

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setActive(false);
  }, []);

  useEffect(() => {
    return () => { stop(); };
  }, [stop]);

  return { videoRef, active, error, hardwareExists, detectHardware, start, stop };
}
