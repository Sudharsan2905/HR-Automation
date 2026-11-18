"use client";

import { useEffect, useCallback, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { AIAvatar } from "@/components/session/ai-avatar";
import { CameraPip } from "@/components/session/camera-pip";
import { VoiceWaveform } from "@/components/session/voice-waveform";
import { SessionProgressBar } from "@/components/session/progress-bar";
import { SessionTimer } from "@/components/session/session-timer";
import { useProctoring } from "@/hooks/use-proctoring";
import { useLiveKit } from "@/hooks/use-livekit";
import { useSessionStore } from "@/stores/session-store";
import { useAuthStore } from "@/stores/auth-store";
import { completeSession, getProgress, nextQuestion, startSession } from "@/lib/api/session";
import { toast } from "sonner";
import { AlertTriangle, LogOut, Mic, MicOff, Play, SkipForward, Circle } from "lucide-react";
import { useInterviewRecorder } from "@/hooks/use-interview-recorder";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { InterviewerCard } from "@/components/session/interviewer-card";
import { CaptionOverlay } from "@/components/session/caption-overlay";

export default function SessionPage() {
  const router = useRouter();
  const {
    phase, setPhase,
    totalQuestions, currentIndex, setProgress,
    warnings,
    interviewTitle, interviewerName, candidateName, domainTitle,
    cameraAvailable,
    roomName, token, livekitUrl,
    aiSpeaking: storeAiSpeaking,
    aiPaused,
    finished,
    botActive,
  } = useSessionStore();

  const logout = useAuthStore((s) => s.logout);
  const setSession = useSessionStore((s) => s.setSession);
  useProctoring();
  const [quitOpen, setQuitOpen] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [started, setStarted] = useState(false);
  const [resuming, setResuming] = useState(!roomName);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [aiAnalyser, setAiAnalyser] = useState<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  // Auto-resume after page refresh — store is wiped but backend session is still alive
  useEffect(() => {
    if (roomName) { setResuming(false); return; }
    (async () => {
      try {
        const session = await startSession(true);
        setSession(session.session_id, session.interview_id, session.total_questions, session.current_question_index, {
          cameraAvailable: session.camera_available,
          roomName: session.room_name,
          token: session.token,
          livekitUrl: session.livekit_url,
          interviewTitle: session.interview_title,
          interviewerName: session.interviewer_name,
          candidateName: session.candidate_name,
          domain: session.domain,
          domainTitle: session.domain_title,
        });
      } catch {
        router.replace("/interview/lobby");
      } finally {
        setResuming(false);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // LiveKit connection
  const lk = useLiveKit(
    roomName && token && livekitUrl
      ? { url: livekitUrl, token, publishCamera: cameraAvailable, publishMic: true }
      : null
  );

  // Screen recorder — captures entire candidate screen, saves locally on completion
  const recorder = useInterviewRecorder({
    aiAudioTrack: lk.aiAudioTrack,
    interviewerAudioTrack: lk.interviewerAudioTrack,
  });

  // Determine if AI is currently speaking (from LiveKit active speakers OR store)
  const aiIsSpeaking = lk.aiSpeaking || storeAiSpeaking;

  // Mark interview as started when AI speaks or on resume
  useEffect(() => {
    if (currentIndex > 0 || aiIsSpeaking) setStarted(true);
  }, [currentIndex, aiIsSpeaking]);

  // Detect active interviewer — observers are hidden in LiveKit (hidden=true grant),
  // so any visible interviewer-* participant has actively joined
  const interviewerParticipant = lk.remoteParticipants.find(
    (p) => p.identity.startsWith("interviewer-")
  );
  const interviewerVideo = lk.remoteVideos.find(
    (v) => v.identity.startsWith("interviewer-")
  );
  const interviewerJoined = !!interviewerParticipant;

  // Connect on mount with retry
  useEffect(() => {
    if (!roomName || !token || !livekitUrl || lk.connected) return;

    let cancelled = false;

    const tryConnect = async (attempt: number) => {
      try {
        await lk.connect();
        if (!cancelled) setPhase("connected");
      } catch (err) {
        if (cancelled) return;
        if (attempt < 3) {
          await new Promise((r) => setTimeout(r, 2000));
          if (cancelled) return;
          await tryConnect(attempt + 1);
        } else {
          console.error("LiveKit connect failed after retries:", err);
          toast.error("Failed to connect to interview room");
        }
      }
    };
    tryConnect(1);

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomName, token, livekitUrl]);

  // Attach local video to ref
  useEffect(() => {
    if (lk.localVideoTrack && videoRef.current) {
      const stream = new MediaStream([lk.localVideoTrack]);
      videoRef.current.srcObject = stream;
    }
  }, [lk.localVideoTrack]);

  // Create AnalyserNode from AI audio track for visualization
  useEffect(() => {
    if (!lk.aiAudioTrack) {
      setAiAnalyser(null);
      return;
    }

    const ctx = audioCtxRef.current || new AudioContext();
    audioCtxRef.current = ctx;

    const stream = new MediaStream([lk.aiAudioTrack]);
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    setAiAnalyser(analyser);

    return () => {
      source.disconnect();
    };
  }, [lk.aiAudioTrack]);

  // Cleanup AudioContext on unmount
  useEffect(() => {
    return () => {
      audioCtxRef.current?.close();
    };
  }, []);

  // Manual mic toggle (available when interviewer has joined)
  const [manualMute, setManualMute] = useState<boolean | null>(null);

  // Reset manual mute when interviewer leaves so auto-mute resumes
  useEffect(() => {
    if (!interviewerJoined) setManualMute(null);
  }, [interviewerJoined]);

  // Auto mute/unmute mic based on AI speaking state (only when interviewer hasn't joined)
  // When interviewer joins, candidate gets manual control
  useEffect(() => {
    if (!lk.connected) return;
    if (interviewerJoined && manualMute !== null) return; // Manual control active
    if (aiIsSpeaking) {
      lk.setMicMuted(true);
    } else if (phase === "connected" && !finished) {
      lk.setMicMuted(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiIsSpeaking, lk.connected, finished, interviewerJoined, manualMute]);

  const toggleMic = useCallback(() => {
    const newMuted = !lk.micMuted;
    lk.setMicMuted(newMuted);
    setManualMute(newMuted);
  }, [lk]);

  // Poll progress every 3s
  useEffect(() => {
    if (phase !== "connected") return;
    const interval = setInterval(async () => {
      try {
        const p = await getProgress();
        setProgress(p.current_question_index, p.ai_speaking, p.ai_paused, p.finished, p.bot_active ?? true);
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [phase, setProgress]);

  // Handle "Start Interview" — signal BE to speak Q1 + start screen recording
  const handleStartInterview = useCallback(async () => {
    setStarted(true);
    setAdvancing(true);
    lk.setMicMuted(true);
    recorder.start(candidateName ?? undefined);
    try {
      await nextQuestion();
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Failed to start");
      setStarted(false);
    } finally {
      setAdvancing(false);
    }
  }, [lk, recorder, candidateName]);

  // Handle "Next Question" — mute mic, signal BE, AI speaks next
  const handleNextQuestion = useCallback(async () => {
    setAdvancing(true);
    lk.setMicMuted(true);
    try {
      await nextQuestion();
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Failed to advance");
    } finally {
      setAdvancing(false);
    }
  }, [lk]);

  // Handle quit — stop recording, complete session, disconnect, logout
  const handleQuit = useCallback(async () => {
    recorder.stop(); // triggers download then clears screen stream
    try {
      await completeSession();
    } catch {}
    lk.disconnect();
    logout();
    router.push("/login");
  }, [lk, logout, router, recorder]);

  // If interview finished (all questions done + closing message), auto-complete
  const completingRef = useRef(false);
  useEffect(() => {
    if (finished && !aiIsSpeaking && phase === "connected" && !completingRef.current) {
      completingRef.current = true;
      (async () => {
        recorder.stop(); // triggers download then clears screen stream
        try {
          await completeSession();
        } catch {
          // OK — might already be completed
        }
        try {
          await lk.disconnect();
        } catch {
          // Suppress "Client initiated disconnect"
        }
        setPhase("completed");
        router.push("/interview/complete");
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished, aiIsSpeaking]);

  // Is it the candidate's turn to answer?
  const isAnswering = lk.connected && !aiIsSpeaking && !finished && !advancing && !aiPaused;

  if (resuming) {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-[#0a0e27] gap-3 text-white/60">
        <div className="h-6 w-6 rounded-full border-2 border-[#00e5ff] border-t-transparent animate-spin" />
        <span className="text-sm">Reconnecting to your session…</span>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-[#0a0e27]">
      {/* AI bot error banner — shown when bot crashed mid-session */}
      {!botActive && !finished && (
        <div className="bg-red-900/90 text-red-200 text-sm text-center py-2 px-4 flex items-center justify-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          AI session lost. Please end the interview and contact your interviewer.
        </div>
      )}

      {/* Warning banner */}
      {warnings >= 3 && (
        <div className="bg-red-500/90 text-white text-sm text-center py-2 px-4 flex items-center justify-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          Multiple tab switches detected. This activity is being logged.
        </div>
      )}

      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
        <SessionProgressBar current={currentIndex} total={totalQuestions} />
        <div className="flex items-center gap-4">
          {recorder.isRecording && (
            <div className="flex items-center gap-1.5 text-xs text-red-400 font-medium">
              <Circle className="h-2 w-2 fill-red-500 text-red-500 animate-pulse" />
              REC
            </div>
          )}
          <SessionTimer />
          <button
            onClick={() => setQuitOpen(true)}
            className="text-white/40 hover:text-red-400 transition-colors"
            title="Quit Interview"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 pb-4 pt-2 min-h-0">
        {/* Interview metadata */}
        {interviewTitle && (
          <div className="text-center w-full max-w-6xl shrink-0">
            <h2 className="text-3xl font-bold text-white tracking-tight">{interviewTitle}</h2>
            <div className="flex items-center justify-center gap-3 mt-2 text-[15px] text-white/60">
              {interviewerName && <span>{interviewerName}</span>}
              {interviewerName && candidateName && <span className="text-white/20">|</span>}
              {candidateName && <span>{candidateName}</span>}
              {domainTitle && (
                <>
                  <span className="text-white/20">|</span>
                  <span className="px-2.5 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/50 text-xs">
                    {domainTitle}
                  </span>
                </>
              )}
            </div>
          </div>
        )}

        {/* Cards grid — fills available height */}
        <div className={`w-full max-w-6xl flex-1 min-h-0 grid gap-4 transition-all duration-300 ${interviewerJoined ? "grid-cols-3" : "grid-cols-2"}`}>
          {/* AI Card */}
          <div className="relative rounded-2xl overflow-hidden neon-card-wrapper">
            <div className="neon-border-glow" />
            <div className="absolute inset-[1px] rounded-2xl bg-[#0d1233] z-[1] flex flex-col items-center justify-center overflow-hidden">
              <div className="absolute top-3 left-3 z-10">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${aiPaused ? "bg-amber-400" : aiIsSpeaking ? "bg-emerald-400 animate-pulse" : "bg-white/30"}`} />
                  <span className="text-xs text-white/50">
                    {aiPaused ? "Paused" : aiIsSpeaking ? "Speaking" : "Listening"}
                  </span>
                </div>
              </div>
              <AIAvatar mode={aiIsSpeaking ? "speaking" : lk.connected ? "listening" : "idle"} analyserNode={aiAnalyser} />
              {aiPaused && (
                <div className="absolute bottom-3 left-0 right-0 text-center z-10">
                  <span className="text-amber-400 text-xs font-medium bg-black/50 px-2 py-1 rounded">AI Paused by Panel</span>
                </div>
              )}
            </div>
          </div>

          {/* Camera / Waveform Card */}
          <div className="relative rounded-2xl overflow-hidden neon-card-wrapper">
            <div className="neon-border-glow" />
            <div className="absolute inset-[1px] rounded-2xl bg-[#0d1233] z-[1] overflow-hidden">
              {cameraAvailable && lk.localVideoTrack ? (
                <CameraPip videoRef={videoRef} active={true} />
              ) : (
                <VoiceWaveform analyserNode={null} isRecording={lk.candidateSpeaking || isAnswering} />
              )}
            </div>
          </div>

          {/* Interviewer Card — appears when interviewer joins actively */}
          {interviewerJoined && interviewerParticipant && (
            <div className="relative rounded-2xl overflow-hidden neon-card-wrapper">
              <div className="neon-border-glow" />
              <div className="absolute inset-[1px] rounded-2xl bg-[#0d1233] z-[1] overflow-hidden">
                <InterviewerCard
                  videoTrack={interviewerVideo?.track ?? null}
                  name={interviewerParticipant.name}
                  isSpeaking={lk.interviewerSpeaking}
                />
              </div>
            </div>
          )}
        </div>

        {/* AI question caption with typewriter effect */}
        <div className="w-full max-w-2xl mx-auto">
          <CaptionOverlay text={lk.caption?.text ?? null} />
        </div>
      </div>

      {/* Neon border animation styles */}
      <style jsx global>{`
        .neon-card-wrapper {
          position: relative;
        }
        .neon-border-glow {
          position: absolute;
          inset: 0;
          border-radius: 1rem;
          background: conic-gradient(
            from var(--neon-angle, 0deg),
            transparent 0%,
            rgba(0, 229, 255, 0.5) 10%,
            rgba(124, 58, 237, 0.4) 20%,
            transparent 30%,
            transparent 70%,
            rgba(0, 229, 255, 0.3) 80%,
            rgba(124, 58, 237, 0.5) 90%,
            transparent 100%
          );
          animation: neon-rotate 4s linear infinite;
        }
        @keyframes neon-rotate {
          from { --neon-angle: 0deg; }
          to { --neon-angle: 360deg; }
        }
        @property --neon-angle {
          syntax: "<angle>";
          initial-value: 0deg;
          inherits: false;
        }

      `}</style>

      {/* Bottom controls */}
      <div className="flex items-center justify-center gap-4 p-4 border-t border-white/10 bg-[#0a0e27]/90">
        {/* Mic — toggleable button when interviewer joined, status indicator otherwise */}
        {interviewerJoined ? (
          <button
            onClick={toggleMic}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-colors ${
              lk.micMuted
                ? "border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20"
                : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
            }`}
          >
            {lk.micMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            <span className="text-sm">{lk.micMuted ? "Unmute" : "Mute"}</span>
          </button>
        ) : (
          <div className="flex items-center gap-2 text-sm text-white/50">
            {lk.micMuted ? (
              <>
                <MicOff className="h-4 w-4 text-red-400" />
                <span className="text-red-400/70">Mic off</span>
              </>
            ) : (
              <>
                <Mic className="h-4 w-4 text-emerald-400" />
                <span className="text-emerald-400/70">Recording</span>
              </>
            )}
          </div>
        )}

        {/* Start Interview button (before first question) */}
        {!started && lk.connected && !aiIsSpeaking && !finished && !aiPaused && botActive && !advancing && (
          <Button
            onClick={handleStartInterview}
            className="bg-[#00e5ff] hover:bg-[#00c4d9] text-[#0a0e27] font-semibold gap-2"
            size="lg"
          >
            <Play className="h-5 w-5" />
            Start Interview
          </Button>
        )}

        {/* Next Question / Done button (after first question is asked) */}
        {started && isAnswering && botActive && !advancing && (
          <Button
            onClick={handleNextQuestion}
            className="bg-[#00e5ff] hover:bg-[#00c4d9] text-[#0a0e27] font-semibold gap-2"
            size="lg"
          >
            <SkipForward className="h-5 w-5" />
            {currentIndex >= totalQuestions - 1 ? "Done" : "Next Question"}
          </Button>
        )}

        {/* Ring loader — while waiting for AI to start speaking after button click */}
        {advancing && !aiPaused && (
          <div className="flex flex-col items-center gap-2">
            <div className="relative h-10 w-10">
              <div className="absolute inset-0 rounded-full border-2 border-[#00e5ff]/15" />
              <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[#00e5ff] animate-spin" />
            </div>
            <span className="text-xs text-[#00e5ff]/60 tracking-wide">Suvera is preparing...</span>
          </div>
        )}

        {/* AI speaking indicator */}
        {aiIsSpeaking && !advancing && !aiPaused && (
          <div className="text-sm text-[#00e5ff]/70 animate-pulse">
            Suvera is speaking...
          </div>
        )}

        {/* AI Paused by interviewer */}
        {aiPaused && (
          <div className="text-sm text-amber-400/80 font-medium">
            AI paused by interviewer
          </div>
        )}

      </div>

      <ConfirmDialog
        open={quitOpen}
        onOpenChange={setQuitOpen}
        title="Quit Interview?"
        description="Your progress will be lost and you will be logged out. Are you sure?"
        confirmLabel="Quit"
        variant="destructive"
        onConfirm={handleQuit}
      />
    </div>
  );
}
