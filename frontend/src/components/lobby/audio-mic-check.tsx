"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { CheckCircle, Lock, Volume2, Loader2, RefreshCw, Mic, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { getAudioCheck } from "@/lib/api/session";
import { useSessionStore } from "@/stores/session-store";
import type { AudioCheckData } from "@/lib/api/session";

type Phase =
  | "idle"
  | "initializing"
  | "speaking"
  | "heard_prompt"
  | "speaker_done"
  | "capturing"   // 4-second VAD capture window
  | "done"
  | "failed";

// RMS threshold for speech detection (0–127 range from getByteTimeDomainData centred at 128)
const RMS_THRESHOLD = 8;
// Cumulative frames above threshold needed
const MIN_SPEECH_FRAMES = 8;
// Capture window duration (ms)
const CAPTURE_DURATION_MS = 7_000;

interface Props {
  passed: boolean;
  disabled?: boolean;
  onPass: (joke: { question: string; punchline: string }) => void;
  preloadedData?: AudioCheckData | null;
}

export function AudioMicCheck({ passed, disabled, onPass, preloadedData }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [joke, setJoke] = useState<{ question: string; punchline: string } | null>(null);
  const [questionAudioUrl, setQuestionAudioUrl] = useState<string | null>(null);
  const [typedText, setTypedText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showTips, setShowTips] = useState(false);
  const [captureProgress, setCaptureProgress] = useState(0);

  const jokeRef = useRef<{ question: string; punchline: string } | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const typingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const responseAudioUrlRef = useRef<string | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // Release all resources on unmount
  useEffect(() => {
    return () => {
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      audioCtxRef.current?.close();
    };
  }, []);

  // 4-second progress bar animation during capture phase
  useEffect(() => {
    if (phase !== "capturing") { setCaptureProgress(0); return; }
    const start = Date.now();
    const id = setInterval(() => {
      const pct = Math.min((Date.now() - start) / CAPTURE_DURATION_MS * 100, 100);
      setCaptureProgress(pct);
      if (pct >= 100) clearInterval(id);
    }, 40);
    return () => clearInterval(id);
  }, [phase]);

  // ── Step 1: request mic + load joke data
  const startCheck = useCallback(async () => {
    setPhase("initializing");
    setError(null);
    setTypedText("");

    const [micResult, jokeResult] = await Promise.allSettled([
      navigator.mediaDevices.getUserMedia({ audio: true, video: false }),
      preloadedData ? Promise.resolve(preloadedData) : getAudioCheck(),
    ]);

    if (micResult.status === "rejected") {
      setError("Microphone access is required. Please allow it in your browser and try again.");
      setPhase("failed");
      return;
    }
    if (jokeResult.status === "rejected") {
      micResult.value.getTracks().forEach((t) => t.stop());
      setError("Couldn't load the audio test. Check your connection and try again.");
      setPhase("failed");
      return;
    }

    useSessionStore.getState().setPreparedAudioCheck(null);

    micStreamRef.current = micResult.value;
    const data = jokeResult.value;
    const j = { question: data.question, punchline: data.punchline };
    setJoke(j);
    jokeRef.current = j;
    setQuestionAudioUrl(`data:audio/mp3;base64,${data.question_audio}`);
    responseAudioUrlRef.current = `data:audio/mp3;base64,${data.response_audio}`;
    setPhase("speaking");
  }, [preloadedData]);

  // ── Replay speaker audio
  const replayAudio = useCallback(() => {
    if (!questionAudioUrl) return;
    audioRef.current?.pause();
    const audio = new Audio(questionAudioUrl);
    audioRef.current = audio;
    audio.play().catch(() => {});
  }, [questionAudioUrl]);

  // ── Auto-play question audio when entering "speaking"
  useEffect(() => {
    if (phase !== "speaking" || !questionAudioUrl) return;
    const audio = new Audio(questionAudioUrl);
    audioRef.current = audio;
    audio.play().catch(() => {});
    return () => { audio.pause(); };
  }, [phase, questionAudioUrl]);

  // ── Typewriter effect while speaking
  useEffect(() => {
    if (phase !== "speaking" || !joke) return;
    let i = 0;
    const full = joke.question;
    typingIntervalRef.current = setInterval(() => {
      i++;
      setTypedText(full.slice(0, i));
      if (i >= full.length) {
        clearInterval(typingIntervalRef.current!);
        setTimeout(() => setPhase("heard_prompt"), 2000);
      }
    }, 42);
    return () => {
      if (typingIntervalRef.current) clearInterval(typingIntervalRef.current);
    };
  }, [phase, joke]);

  // ── Stop VAD and release mic
  const stopListening = useCallback((stream: MediaStream) => {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    animFrameRef.current = null;
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    stream.getTracks().forEach((t) => t.stop());
    micStreamRef.current = null;
  }, []);

  // ── Step 2: 4-second capture window with VAD
  const beginListening = useCallback(async () => {
    setPhase("capturing");
    setError(null);

    // Always acquire a fresh stream for the mic test — the one from startCheck
    // may have degraded after the speaker audio played
    micStreamRef.current?.getTracks().forEach((t) => t.stop());
    micStreamRef.current = null;

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      micStreamRef.current = stream;
    } catch {
      setError("Mic not accessible. Grant permission and try again.");
      setPhase("failed");
      return;
    }

    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    if (ctx.state === "suspended") await ctx.resume();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    const buffer = new Uint8Array(analyser.fftSize);
    let speechFrames = 0;
    const deadline = Date.now() + CAPTURE_DURATION_MS;

    const tick = () => {
      analyser.getByteTimeDomainData(buffer);
      let sum = 0;
      for (const v of buffer) sum += (v - 128) ** 2;
      const rms = Math.sqrt(sum / buffer.length);

      if (rms > RMS_THRESHOLD) speechFrames++;

      if (Date.now() >= deadline) {
        // Full window elapsed — decide based on accumulated speech frames
        stopListening(stream);
        if (speechFrames >= MIN_SPEECH_FRAMES) {
          if (responseAudioUrlRef.current) {
            new Audio(responseAudioUrlRef.current).play().catch(() => {});
          }
          setPhase("done");
          if (jokeRef.current) onPass(jokeRef.current);
        } else {
          setError("We didn't pick up any sound. Make sure your mic isn't muted and try again.");
          setPhase("failed");
        }
        return;
      }

      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);
  }, [onPass, stopListening]);

  // ── Reset to idle
  const reset = useCallback(() => {
    micStreamRef.current?.getTracks().forEach((t) => t.stop());
    micStreamRef.current = null;
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    animFrameRef.current = null;
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    if (typingIntervalRef.current) clearInterval(typingIntervalRef.current);
    setPhase("idle");
    setTypedText("");
    setError(null);
    setCaptureProgress(0);
  }, []);

  // ─────────────────────────────────────────────
  // Already passed — simple locked row
  if (passed) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-green-500/30 bg-green-500/5 p-4">
        <CheckCircle className="h-5 w-5 text-green-500 shrink-0" />
        <span className="text-green-400">Mic &amp; Speaker Test</span>
      </div>
    );
  }

  // Locked until previous step is done
  if (disabled) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-4">
        <div className="flex items-center gap-3">
          <Lock className="h-5 w-5 text-white/25 shrink-0" />
          <span className="text-sm text-white/25">Mic &amp; Speaker Test — complete camera check first</span>
        </div>
      </div>
    );
  }

  const expanded = phase !== "idle";
  const speakerLocked = ["speaker_done", "capturing", "done"].includes(phase);
  const micVisible = ["speaker_done", "capturing", "done"].includes(phase);
  const allDone = phase === "done";

  return (
    <div className={cn(
      "rounded-lg border transition-colors duration-300",
      allDone ? "border-green-500/30 bg-green-500/5" : "border-white/10 bg-white/5"
    )}>

      {/* ── Card header */}
      <div className="flex items-center justify-between p-4">
        <div className="flex items-center gap-3">
          {allDone
            ? <CheckCircle className="h-5 w-5 text-green-500" />
            : <Volume2 className={cn("h-5 w-5", expanded ? "text-[#00e5ff]" : "text-white/30")} />
          }
          <span className={cn(
            "text-sm font-medium",
            allDone ? "text-green-400" : expanded ? "text-white" : "text-white/60"
          )}>
            Mic &amp; Speaker Test
          </span>
        </div>
        {phase === "idle" && (
          <Button size="sm" onClick={startCheck} className="bg-[#00e5ff] text-slate-950 hover:bg-[#00e5ff]/80">
            Start Test <ChevronDown className="ml-1.5 h-3.5 w-3.5" />
          </Button>
        )}
        {phase === "initializing" && (
          <Loader2 className="h-4 w-4 animate-spin text-white/40" />
        )}
      </div>

      {/* ── Expanded body */}
      {expanded && (
        <div className="px-4 pb-4 space-y-2.5">

          {/* ── SPEAKER section */}
          <div className={cn(
            "rounded-lg border p-3.5 space-y-3 transition-all duration-500",
            speakerLocked
              ? "border-green-500/20 bg-green-500/5"
              : "border-[#00e5ff]/20 bg-[#00e5ff]/5"
          )}>
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-white/50 uppercase tracking-wider">
                🔊 Speaker Check
              </p>
              {speakerLocked
                ? <CheckCircle className="h-4 w-4 text-green-500" />
                : phase === "initializing"
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin text-white/30" />
                  : null
              }
            </div>

            {(phase === "speaking" || phase === "heard_prompt") && (
              <p className={cn(
                "text-sm font-medium leading-relaxed transition-colors duration-700 min-h-[1.5rem]",
                phase === "heard_prompt" ? "text-white/30" : "text-white"
              )}>
                {typedText}
                {phase === "speaking" && (
                  <span className="inline-block w-0.5 h-[0.9em] bg-[#00e5ff] ml-0.5 align-middle animate-pulse" />
                )}
              </p>
            )}

            {speakerLocked && joke && (
              <p className="text-sm text-white/25 leading-relaxed">{joke.question}</p>
            )}

            {phase === "heard_prompt" && (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => setPhase("speaker_done")}
                    className="flex-1 bg-emerald-500 hover:bg-emerald-600 text-white font-semibold"
                  >
                    Yes, I Heard It ✓
                  </Button>
                  <button
                    onClick={() => { setShowTips((s) => !s); replayAudio(); }}
                    className="flex-1 rounded-md bg-white/10 hover:bg-white/15 border border-white/20 text-white/70 text-sm font-medium transition-colors px-3 py-1.5"
                  >
                    Didn&apos;t Hear It
                  </button>
                </div>
                {showTips && (
                  <ul className="text-xs text-white/50 space-y-1.5 list-disc pl-4 bg-white/5 rounded-lg p-3 border border-white/10">
                    <li>Turn up your system volume</li>
                    <li>Check headphones or speakers are connected</li>
                    <li>Make sure the browser tab isn&apos;t muted (speaker icon in the tab bar)</li>
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* ── MIC section — locked placeholder */}
          {!micVisible && phase !== "initializing" && (
            <div className="rounded-lg border border-white/5 bg-black/10 p-3.5 flex items-center gap-2.5">
              <Lock className="h-3.5 w-3.5 text-white/25 shrink-0" />
              <p className="text-xs text-white/25">Mic check — unlocks after speaker test</p>
            </div>
          )}

          {/* ── MIC section — active */}
          {micVisible && joke && (
            <div className={cn(
              "rounded-lg border p-3.5 space-y-3 transition-all duration-500",
              allDone
                ? "border-green-500/20 bg-green-500/5"
                : "border-[#00e5ff]/20 bg-[#00e5ff]/5"
            )}>
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-white/50 uppercase tracking-wider">
                  🎙️ Mic Check
                </p>
                {allDone && <CheckCircle className="h-4 w-4 text-green-500" />}
              </div>

              {!allDone && (
                <div className="space-y-1">
                  <p className="text-xs text-white/40">Say this aloud into your mic:</p>
                  <p className={cn(
                    "text-base font-semibold leading-snug transition-colors",
                    phase === "capturing" ? "text-[#00e5ff]" : "text-white"
                  )}>
                    {joke.punchline}
                  </p>
                </div>
              )}

              {phase === "speaker_done" && (
                <Button
                  onClick={beginListening}
                  className="w-full bg-[#00e5ff] hover:bg-[#00c4d9] text-slate-950 font-semibold gap-2"
                >
                  <Mic className="h-4 w-4" /> Start Mic Test
                </Button>
              )}

              {phase === "capturing" && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-[#00e5ff]/80">
                    <div className="h-1.5 w-1.5 rounded-full bg-[#00e5ff] animate-pulse" />
                    Capturing audio — say the punchline now!
                  </div>
                  <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#00e5ff] rounded-full transition-none"
                      style={{ width: `${captureProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {allDone && (
                <p className="text-sm text-green-300 leading-relaxed">
                  😂 Ha haa! Got your joke! Your mic and speaker are working perfectly. All the best for your interview, go ahead!
                </p>
              )}
            </div>
          )}

          {/* ── Failed state */}
          {phase === "failed" && (
            <div className="space-y-2 pt-1">
              <p className="text-sm text-red-400">{error}</p>
              <button
                onClick={reset}
                className="flex items-center gap-1.5 text-xs text-white/40 hover:text-white/60 transition-colors"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Try Again
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
