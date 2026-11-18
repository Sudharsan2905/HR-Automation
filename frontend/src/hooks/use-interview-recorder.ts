"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { getScreenStream, clearScreenStream } from "@/lib/screen-capture";

interface RecorderOptions {
  aiAudioTrack: MediaStreamTrack | null;
  interviewerAudioTrack: MediaStreamTrack | null;
}

export function useInterviewRecorder({ aiAudioTrack, interviewerAudioTrack }: RecorderOptions) {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const destinationRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const connectedRef = useRef<Set<MediaStreamTrack>>(new Set());
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const filenameRef = useRef<string>("interview-recording.webm");
  const [isRecording, setIsRecording] = useState(false);

  const connectAudio = useCallback((track: MediaStreamTrack) => {
    const ctx = audioCtxRef.current;
    const dest = destinationRef.current;
    if (!ctx || !dest || connectedRef.current.has(track)) return;
    ctx.createMediaStreamSource(new MediaStream([track])).connect(dest);
    connectedRef.current.add(track);
  }, []);

  // Dynamically wire in AI audio the moment it arrives (or recording starts)
  useEffect(() => {
    if (isRecording && aiAudioTrack) connectAudio(aiAudioTrack);
  }, [aiAudioTrack, isRecording, connectAudio]);

  // Dynamically wire in interviewer audio if they join mid-session
  useEffect(() => {
    if (isRecording && interviewerAudioTrack) connectAudio(interviewerAudioTrack);
  }, [interviewerAudioTrack, isRecording, connectAudio]);

  const start = useCallback(async (candidateName?: string) => {
    if (isRecording || mediaRecorderRef.current) return;

    const screenStream = getScreenStream();
    if (!screenStream) {
      console.error("[Recorder] No screen stream — lobby check must have been skipped");
      return;
    }

    // Build filename from candidate name + date
    const name = (candidateName ?? "candidate").replace(/\s+/g, "-").toLowerCase();
    const date = new Date().toISOString().split("T")[0];
    filenameRef.current = `interview-${name}-${date}.webm`;

    const ctx = new AudioContext();
    const destination = ctx.createMediaStreamDestination();
    audioCtxRef.current = ctx;
    destinationRef.current = destination;
    connectedRef.current = new Set();

    // Mic audio — permission already granted in lobby so no extra prompt
    try {
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      micStreamRef.current = micStream;
      ctx.createMediaStreamSource(micStream).connect(destination);
      micStream.getAudioTracks().forEach((t) => connectedRef.current.add(t));
    } catch {
      console.warn("[Recorder] Mic unavailable — recording without candidate audio");
    }

    // Connect any already-available remote tracks
    if (aiAudioTrack) connectAudio(aiAudioTrack);
    if (interviewerAudioTrack) connectAudio(interviewerAudioTrack);

    // Combine screen video + mixed audio into the recording stream
    const recordStream = new MediaStream();
    screenStream.getVideoTracks().forEach((t) => recordStream.addTrack(t));
    destination.stream.getAudioTracks().forEach((t) => recordStream.addTrack(t));

    const mimeType =
      ["video/webm;codecs=vp8,opus", "video/webm;codecs=vp9,opus", "video/webm"].find((m) =>
        MediaRecorder.isTypeSupported(m)
      ) ?? "";

    chunksRef.current = [];
    const recorder = new MediaRecorder(recordStream, mimeType ? { mimeType } : undefined);

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      const type = recorder.mimeType?.split(";")[0] || "video/webm";
      const blob = new Blob(chunksRef.current, { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filenameRef.current;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 2000);

      // Release mic and audio graph
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
      destinationRef.current = null;
      connectedRef.current = new Set();
      mediaRecorderRef.current = null;

      // Release screen share
      clearScreenStream();
      setIsRecording(false);
    };

    mediaRecorderRef.current = recorder;
    recorder.start(1000); // collect chunks every 1 s
    setIsRecording(true);
  }, [isRecording, aiAudioTrack, interviewerAudioTrack, connectAudio]);

  const stop = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop(); // triggers onstop → download
  }, []);

  // Safety cleanup on unmount (e.g., hard refresh during session)
  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state !== "inactive") {
        mediaRecorderRef.current?.stop();
      }
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close();
    };
  }, []);

  return { isRecording, start, stop };
}
