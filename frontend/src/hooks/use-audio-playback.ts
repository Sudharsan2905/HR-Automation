"use client";

import { useRef, useState, useCallback } from "react";

export function useAudioPlayback() {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const [playing, setPlaying] = useState(false);
  const [analyserNode, setAnalyserNode] = useState<AnalyserNode | null>(null);

  // Pre-initialize AudioContext on user gesture (call on "Start Interview" click)
  // This warms the audio pipeline so the first play() has zero cold-start delay
  const init = useCallback(async () => {
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") return;
    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    if (ctx.state === "suspended") await ctx.resume();
    // Play a tiny silent buffer to fully warm the output pipeline
    const silent = ctx.createBuffer(1, ctx.sampleRate * 0.05, ctx.sampleRate);
    const src = ctx.createBufferSource();
    src.buffer = silent;
    src.connect(ctx.destination);
    src.start();
  }, []);

  const play = useCallback(async (base64: string): Promise<void> => {
    return new Promise(async (resolve) => {
      try {
        // Stop any existing playback
        if (sourceRef.current) {
          try { sourceRef.current.stop(); } catch {}
          sourceRef.current = null;
        }

        // Reuse existing context (from init), or create if somehow missing
        if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
          audioCtxRef.current = new AudioContext();
        }
        const audioCtx = audioCtxRef.current;
        if (audioCtx.state === "suspended") {
          await audioCtx.resume();
        }

        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 2048;
        setAnalyserNode(analyser);

        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));

        const source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(analyser);
        analyser.connect(audioCtx.destination);
        sourceRef.current = source;

        setPlaying(true);
        source.onended = () => {
          setPlaying(false);
          setAnalyserNode(null);
          resolve();
        };
        source.start();
      } catch (err) {
        console.error("Audio playback error:", err);
        setPlaying(false);
        setAnalyserNode(null);
        resolve();
      }
    });
  }, []);

  const stop = useCallback(() => {
    try { sourceRef.current?.stop(); } catch {}
    sourceRef.current = null;
    setAnalyserNode(null);
    setPlaying(false);
  }, []);

  const cleanup = useCallback(() => {
    stop();
    try { audioCtxRef.current?.close(); } catch {}
    audioCtxRef.current = null;
  }, [stop]);

  return { playing, analyserNode, init, play, stop, cleanup };
}
