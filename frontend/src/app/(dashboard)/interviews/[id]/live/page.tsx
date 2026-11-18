"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useLiveKit } from "@/hooks/use-livekit";
import { AIAvatar } from "@/components/session/ai-avatar";
import { VoiceWaveform } from "@/components/session/voice-waveform";
import { getWatchToken, joinAsInterviewer, interviewerPauseAi, interviewerResumeAi } from "@/lib/api/session";
import { getInterview } from "@/lib/api/interviews";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { ArrowLeft, Pause, Play, UserPlus, PhoneOff, Mic, MicOff, Video, VideoOff } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import type { InterviewDetail } from "@/types/interview";
import { createLocalTracks, Track } from "livekit-client";

function RemoteVideo({ track }: { track: MediaStreamTrack }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.srcObject = new MediaStream([track]);
    }
  }, [track]);
  return (
    <video ref={ref} autoPlay playsInline muted className="w-full h-full object-cover" style={{ transform: "scaleX(-1)" }} />
  );
}

export default function LiveObservationPage() {
  const params = useParams();
  const router = useRouter();
  const interviewId = params.id as string;
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "super_admin";

  const [interview, setInterview] = useState<InterviewDetail | null>(null);
  const [roomInfo, setRoomInfo] = useState<{ room_name: string; token: string; livekit_url: string } | null>(null);
  const [joined, setJoined] = useState(false);
  const [aiPaused, setAiPaused] = useState(false);
  const [loading, setLoading] = useState(true);
  const [localMicOn, setLocalMicOn] = useState(false);
  const [localCamOn, setLocalCamOn] = useState(false);
  const [myVideoTrack, setMyVideoTrack] = useState<MediaStreamTrack | null>(null);
  const [aiAnalyser, setAiAnalyser] = useState<AnalyserNode | null>(null);
  const [candidateAnalyser, setCandidateAnalyser] = useState<AnalyserNode | null>(null);
  const localVideoRef = useRef<HTMLVideoElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  const lk = useLiveKit(
    roomInfo
      ? { url: roomInfo.livekit_url, token: roomInfo.token, publishCamera: false, publishMic: false }
      : null
  );

  // Load interview + get watch token (cancelled flag prevents StrictMode double-fetch race)
  useEffect(() => {
    let cancelled = false;
    Promise.all([getInterview(interviewId), getWatchToken(interviewId)])
      .then(([iv, token]) => {
        if (cancelled) return;
        setInterview(iv);
        setRoomInfo(token);
      })
      .catch((err) => {
        if (cancelled) return;
        toast.error((err as { message?: string })?.message || "Failed to load");
        router.push("/hiring");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [interviewId, router]);

  // Connect once we have room info
  useEffect(() => {
    if (!roomInfo || lk.connected) return;

    let cancelled = false;

    const tryConnect = async (attempt: number) => {
      try {
        await lk.connect();
      } catch (err) {
        if (cancelled) return;
        if (attempt < 3) {
          await new Promise((r) => setTimeout(r, 2000));
          if (cancelled) return;
          await tryConnect(attempt + 1);
        } else {
          console.error("LiveKit connect failed after retries:", err);
          toast.error("Failed to connect to room");
        }
      }
    };
    tryConnect(1);

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomInfo]);

  // Create AnalyserNode from AI audio track
  useEffect(() => {
    if (!lk.aiAudioTrack) { setAiAnalyser(null); return; }
    const ctx = audioCtxRef.current || new AudioContext();
    audioCtxRef.current = ctx;
    const stream = new MediaStream([lk.aiAudioTrack]);
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    setAiAnalyser(analyser);
    return () => { source.disconnect(); };
  }, [lk.aiAudioTrack]);

  // Create AnalyserNode from candidate audio track
  useEffect(() => {
    if (!lk.candidateAudioTrack) { setCandidateAnalyser(null); return; }
    const ctx = audioCtxRef.current || new AudioContext();
    audioCtxRef.current = ctx;
    const stream = new MediaStream([lk.candidateAudioTrack]);
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    setCandidateAnalyser(analyser);
    return () => { source.disconnect(); };
  }, [lk.candidateAudioTrack]);

  // Cleanup AudioContext
  useEffect(() => {
    return () => { audioCtxRef.current?.close(); };
  }, []);

  // Attach local video when track changes
  useEffect(() => {
    if (myVideoTrack && localVideoRef.current) {
      localVideoRef.current.srcObject = new MediaStream([myVideoTrack]);
    }
  }, [myVideoTrack]);

  // Release hardware on tab close / navigation
  useEffect(() => {
    const cleanup = () => {
      const room = lk.room;
      if (room) {
        room.localParticipant.audioTrackPublications.forEach((pub) => pub.track?.stop());
        room.localParticipant.videoTrackPublications.forEach((pub) => pub.track?.stop());
      }
    };
    window.addEventListener("beforeunload", cleanup);
    return () => window.removeEventListener("beforeunload", cleanup);
  }, [lk.room]);

  // Join as active participant — disconnect observer, reconnect with active token
  const handleJoin = useCallback(async () => {
    try {
      const res = await joinAsInterviewer(interviewId);
      await lk.disconnect();
      setRoomInfo(res);
      setJoined(true);
      toast.success("Joined as active participant");
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Failed to join");
    }
  }, [interviewId, lk]);

  // Toggle mic after joining
  const toggleMic = useCallback(async () => {
    const room = lk.room;
    if (!room) return;
    try {
      if (localMicOn) {
        room.localParticipant.audioTrackPublications.forEach((pub) => {
          pub.track?.mute();
        });
        setLocalMicOn(false);
      } else {
        const existing = Array.from(room.localParticipant.audioTrackPublications.values());
        if (existing.length > 0) {
          existing.forEach((pub) => pub.track?.unmute());
        } else {
          const tracks = await createLocalTracks({ audio: true, video: false });
          for (const t of tracks) {
            await room.localParticipant.publishTrack(t);
          }
        }
        setLocalMicOn(true);
      }
    } catch (err) {
      toast.error("Failed to access microphone");
      console.error("toggleMic error:", err);
    }
  }, [lk.room, localMicOn]);

  // Toggle camera after joining
  const toggleCam = useCallback(async () => {
    const room = lk.room;
    if (!room) return;
    try {
      if (localCamOn) {
        room.localParticipant.videoTrackPublications.forEach((pub) => {
          if (pub.track) {
            pub.track.stop();
            room.localParticipant.unpublishTrack(pub.track);
          }
        });
        setLocalCamOn(false);
        setMyVideoTrack(null);
      } else {
        const tracks = await createLocalTracks({ audio: false, video: true });
        for (const t of tracks) {
          await room.localParticipant.publishTrack(t);
          if (t.kind === Track.Kind.Video) {
            setMyVideoTrack(t.mediaStreamTrack);
          }
        }
        setLocalCamOn(true);
      }
    } catch (err) {
      toast.error("Failed to access camera");
      console.error("toggleCam error:", err);
    }
  }, [lk.room, localCamOn]);

  const handlePauseResume = useCallback(async () => {
    try {
      if (aiPaused) {
        await interviewerResumeAi(interviewId);
        setAiPaused(false);
      } else {
        await interviewerPauseAi(interviewId);
        setAiPaused(true);
      }
    } catch {
      toast.error("Failed to toggle AI");
    }
  }, [interviewId, aiPaused]);

  const handleLeave = useCallback(() => {
    // Stop all local tracks to release hardware before disconnecting
    const room = lk.room;
    if (room) {
      room.localParticipant.audioTrackPublications.forEach((pub) => {
        if (pub.track) {
          pub.track.stop();
          room.localParticipant.unpublishTrack(pub.track);
        }
      });
      room.localParticipant.videoTrackPublications.forEach((pub) => {
        if (pub.track) {
          pub.track.stop();
          room.localParticipant.unpublishTrack(pub.track);
        }
      });
    }
    setMyVideoTrack(null);
    lk.disconnect();
    router.push(`/interviews/${interviewId}`);
  }, [lk, router, interviewId]);

  const candidateVideo = lk.remoteVideos.find((v) => v.identity.startsWith("candidate-"));
  const myIdentity = lk.room?.localParticipant.identity ?? "";
  const remoteInterviewers = lk.remoteParticipants.filter(
    (p) => p.identity.startsWith("interviewer-") && p.identity !== myIdentity && p.canPublish
  );
  const totalCards = 2 + remoteInterviewers.length + (joined ? 1 : 0);
  const gridClass =
    totalCards <= 2 ? "grid-cols-2 grid-rows-1" :
    totalCards === 3 ? "grid-cols-3 grid-rows-1" :
    "grid-cols-2 grid-rows-2";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)] gap-3 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => router.push("/hiring")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold">{interview?.domain_title || "Live Interview"}</h1>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 uppercase tracking-wider">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Live
              </span>
            </div>
            <p className="text-sm text-muted-foreground">
              {interview?.candidate_name} &middot; {!isAdmin && joined ? "Active Participant" : "Observing"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {!isAdmin && !joined && (
            <Button onClick={handleJoin} variant="outline" className="gap-2">
              <UserPlus className="h-4 w-4" /> Join Interview
            </Button>
          )}
          {!isAdmin && joined && (
            <>
              <Button onClick={toggleMic} variant="outline" size="icon" title={localMicOn ? "Mute mic" : "Unmute mic"}>
                {localMicOn ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4 text-red-500" />}
              </Button>
              <Button onClick={toggleCam} variant="outline" size="icon" title={localCamOn ? "Turn off camera" : "Turn on camera"}>
                {localCamOn ? <Video className="h-4 w-4" /> : <VideoOff className="h-4 w-4 text-red-500" />}
              </Button>
            </>
          )}
          {!isAdmin && (
            <Button onClick={handlePauseResume} variant="outline" className="gap-2">
              {aiPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
              {aiPaused ? "Resume AI" : "Pause AI"}
            </Button>
          )}
          <Button onClick={handleLeave} variant="destructive" className="gap-2">
            <PhoneOff className="h-4 w-4" /> Leave
          </Button>
        </div>
      </div>

      {/* Cards grid — fills all available space */}
      <div className={`flex-1 min-h-0 grid gap-4 ${gridClass}`}>
        {/* AI Card */}
        <div className="relative rounded-2xl overflow-hidden bg-[#0d1233] border border-white/10">
          <div className="absolute top-3 left-3 z-10">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${aiPaused ? "bg-amber-400" : lk.aiSpeaking ? "bg-emerald-400 animate-pulse" : "bg-white/30"}`} />
              <span className="text-xs text-white/50">
                {aiPaused ? "Paused" : lk.aiSpeaking ? "Speaking" : "Listening"}
              </span>
            </div>
          </div>
          <div className="w-full h-full flex items-center justify-center">
            <AIAvatar mode={lk.aiSpeaking ? "speaking" : lk.connected ? "listening" : "idle"} analyserNode={aiAnalyser} />
          </div>
          {aiPaused && (
            <div className="absolute bottom-3 left-0 right-0 text-center">
              <span className="text-amber-400 text-xs font-medium bg-black/50 px-2 py-1 rounded">AI Paused</span>
            </div>
          )}
        </div>

        {/* Candidate Card */}
        <div className="relative rounded-2xl overflow-hidden bg-[#0d1233] border border-white/10">
          {candidateVideo ? (
            <RemoteVideo track={candidateVideo.track} />
          ) : (
            <div className="w-full h-full">
              <VoiceWaveform analyserNode={candidateAnalyser} isRecording={lk.candidateSpeaking} label={interview?.candidate_name || "Candidate"} />
            </div>
          )}
          <span className="absolute bottom-3 left-3 text-sm font-medium text-white/40 tracking-wide bg-black/40 px-2.5 py-1 rounded-md z-10">
            {interview?.candidate_name || "Candidate"}
          </span>
        </div>

        {/* Remote active interviewer cards (panel or admin on the other side) */}
        {remoteInterviewers.map((p) => {
          const remoteVideo = lk.remoteVideos.find((v) => v.identity === p.identity);
          return (
            <div key={p.identity} className="relative rounded-2xl overflow-hidden bg-[#0d1233] border border-white/10">
              {remoteVideo ? (
                <RemoteVideo track={remoteVideo.track} />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center gap-3">
                  <div className="h-16 w-16 rounded-full bg-white/10 flex items-center justify-center">
                    <span className="text-2xl text-white/50">{p.name?.[0] ?? "P"}</span>
                  </div>
                </div>
              )}
              <span className="absolute bottom-3 left-3 text-sm font-medium text-white/40 tracking-wide bg-black/40 px-2.5 py-1 rounded-md z-10">
                {p.name || "Panel"}
              </span>
            </div>
          );
        })}

        {/* You card (only after joining — never for admin) */}
        {!isAdmin && joined && (
          <div className="relative rounded-2xl overflow-hidden bg-[#0d1233] border border-white/10">
            {localCamOn && myVideoTrack ? (
              <video
                ref={localVideoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
                style={{ transform: "scaleX(-1)" }}
              />
            ) : (
              <div className="w-full h-full flex flex-col items-center justify-center gap-3">
                <div className={`h-16 w-16 rounded-full bg-white/10 flex items-center justify-center transition-shadow ${lk.interviewerSpeaking && localMicOn ? "shadow-[0_0_20px_rgba(52,211,153,0.5)]" : ""}`}>
                  <span className="text-2xl text-white/50">You</span>
                </div>
                {localMicOn && lk.interviewerSpeaking ? (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                    <Mic className="h-3 w-3 animate-pulse" />
                    <SpeakingBars />
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-xs text-white/40">
                    {localMicOn ? (
                      <><Mic className="h-3 w-3 text-emerald-400" /><span>Mic on</span></>
                    ) : (
                      <><MicOff className="h-3 w-3 text-red-400" /><span>Mic off</span></>
                    )}
                  </div>
                )}
              </div>
            )}
            <span className="absolute bottom-3 left-3 text-sm font-medium text-white/40 tracking-wide bg-black/40 px-2.5 py-1 rounded-md z-10">
              {isAdmin ? "You (Admin)" : "You (Panel)"}
            </span>
          </div>
        )}

      </div>

      {/* Caption strip — always reserves space so grid height stays stable */}
      <div className="shrink-0 h-20 overflow-hidden flex items-center justify-center">
        {lk.caption && (
          <div className="w-fit max-w-full bg-slate-900/75 backdrop-blur-md border border-white/15 rounded-xl px-5 py-2 overflow-y-auto max-h-full">
            <p className="text-white text-sm">{lk.caption.text}</p>
            {!lk.aiSpeaking && (() => {
              const pts = interview?.questions?.[lk.caption!.questionIndex]?.expected_points;
              return pts && pts.length > 0 ? (
                <div className="flex flex-wrap gap-x-5 gap-y-0.5 mt-1">
                  {pts.map((pt, i) => (
                    <span key={i} className="text-xs text-white/50">&#x2192; {pt}</span>
                  ))}
                </div>
              ) : null;
            })()}
          </div>
        )}
      </div>

      {!lk.connected && (
        <div className="text-center text-muted-foreground text-sm py-4 shrink-0">
          Connecting to interview room...
        </div>
      )}
    </div>
  );
}

function SpeakingBars() {
  return (
    <>
      <div className="flex items-end gap-[2px] h-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className="w-[3px] rounded-full bg-emerald-400 speaking-bar"
            style={{ animationDelay: `${i * 120}ms` }}
          />
        ))}
      </div>
      <style>{`
        .speaking-bar {
          display: inline-block;
          height: 4px;
          animation: speakingBarWave 0.8s ease-in-out infinite;
        }
        @keyframes speakingBarWave {
          0%, 100% { height: 4px; }
          50% { height: 16px; }
        }
      `}</style>
    </>
  );
}
